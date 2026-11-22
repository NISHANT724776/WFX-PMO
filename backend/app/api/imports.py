import csv
import hashlib
import io
import uuid
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.audit import write_audit
from app.core.deps import accessible_project_ids, ensure_project_access, get_db, require
from app.core.storage import get_storage
from app.models import ImportBatch, MappingTemplate, UploadedSheet, User, ValidationIssue
from app.modules.excel_intel import committer, service
from app.modules.excel_intel.catalog import CLASS_LABEL, ENTITIES
from app.modules.excel_intel.reader import UnsafeFileError, check_upload
from app.schemas.common import ORMModel

router = APIRouter()
templates_router = APIRouter()


# ----------------------------------------------------------------- access helpers
def _batch(db: Session, user: User, batch_id: uuid.UUID) -> ImportBatch:
    b = db.get(ImportBatch, batch_id)
    if b is not None and not _can_see(db, user, b):
        b = None
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return b


def _can_see(db: Session, user: User, b: ImportBatch) -> bool:
    if b.uploaded_by == user.id or user.role.is_global_scope:
        return True
    allowed = accessible_project_ids(db, user)
    return b.project_id is not None and allowed is not None and b.project_id in allowed


def _sheet(b: ImportBatch, sheet_id: uuid.UUID) -> UploadedSheet:
    s = next((x for x in b.sheets if x.id == sheet_id), None)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sheet not found")
    return s


def _editable(b: ImportBatch) -> None:
    if b.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Import is '{b.status}'; mappings can only be edited while it is ready")


def _batch_out(db: Session, b: ImportBatch, detail: bool = False) -> dict[str, Any]:
    uploader = db.get(User, b.uploaded_by)
    out: dict[str, Any] = {
        "id": b.id, "filename": b.filename, "size_bytes": b.size_bytes, "status": b.status, "error": b.error,
        "uploaded_by": uploader.email if uploader else None, "uploaded_at": b.created_at, "project_id": b.project_id,
        "purpose": b.purpose, "committed_at": b.committed_at, "commit_summary": b.commit_summary,
        "template": db.get(MappingTemplate, b.template_id).name if b.template_id else None,
    }
    if detail:
        out["sheets"] = [
            {"id": s.id, "name": s.name, "state": s.state, "classification": s.classification,
             "classification_label": CLASS_LABEL.get(s.classification, s.classification), "class_confidence": s.class_confidence,
             "entity": s.entity, "enabled": s.enabled, "rows": s.n_rows, "columns": s.n_cols,
             "template": (s.profile or {}).get("template"), "not_yet": (s.profile or {}).get("not_yet"),
             "unconfirmed": service.effective_mappings(s)[1]}
            for s in b.sheets
        ]
        out["validation"] = (b.meta or {}).get("validation")
    return out


# ----------------------------------------------------------------- upload / list
@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: Optional[uuid.UUID] = Form(None),
    purpose: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require("imports:upload")),
):
    s = get_settings()
    limit = s.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds {s.max_upload_mb} MB")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File is empty")
    name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:300]
    try:
        ext = check_upload(name, data)
    except UnsafeFileError as e:
        write_audit(db, user, "import_rejected", "import_batch", None, after={"filename": name, "reason": str(e)})
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    if project_id is not None:
        ensure_project_access(db, user, project_id)
    sha = hashlib.sha256(data).hexdigest()
    stored = get_storage().save(data, ext)
    b = ImportBatch(filename=name, stored_name=stored, size_bytes=len(data), sha256=sha, ext=ext, uploaded_by=user.id,
                    project_id=None, purpose=purpose, meta={"intended_project_id": str(project_id) if project_id else None})
    db.add(b)
    db.flush()
    prior = db.scalar(select(ImportBatch).where(ImportBatch.sha256 == sha, ImportBatch.status == "committed", ImportBatch.id != b.id))
    write_audit(db, user, "import_upload", "import_batch", b.id, after={"filename": name, "size": len(data), "sha256": sha})
    db.commit()
    background.add_task(service.analyze_batch, b.id)
    out = _batch_out(db, b)
    out["duplicate_of"] = prior.id if prior else None
    return out


@router.get("")
def list_imports(
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(require("imports:read")),
):
    stmt = select(ImportBatch)
    if not user.role.is_global_scope:
        allowed = accessible_project_ids(db, user) or set()
        stmt = stmt.where((ImportBatch.uploaded_by == user.id) | (ImportBatch.project_id.in_(allowed or {uuid.UUID(int=0)})))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(ImportBatch.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    return {"items": [_batch_out(db, b) for b in rows], "total": total, "page": page, "size": size}


@router.get("/{batch_id}")
def get_import(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:read"))):
    return _batch_out(db, _batch(db, user, batch_id), detail=True)


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:upload"))):
    b = _batch(db, user, batch_id)
    if b.status == "committed":
        raise HTTPException(status.HTTP_409_CONFLICT, "A committed import cannot be deleted; roll it back first")
    if b.uploaded_by != user.id and not user.role.is_global_scope:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the uploader can delete this import")
    get_storage().delete(b.stored_name) if b.status != "rolled_back" else None
    write_audit(db, user, "import_delete", "import_batch", b.id, before={"filename": b.filename})
    db.delete(b)
    db.commit()


# ----------------------------------------------------------------- sheet details and editing
@router.get("/{batch_id}/sheets/{sheet_id}")
def get_sheet(batch_id: uuid.UUID, sheet_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:read"))):
    b = _batch(db, user, batch_id)
    s = _sheet(b, sheet_id)
    ent = ENTITIES.get(s.entity) if s.entity else None
    pw_values = []
    if s.entity == "dependency_item":  # distinct raw values of the column mapped to 'pending_with', for the user to classify
        col = next((c for c in s.columns if c.mapping and c.mapping.target_field == "pending_with"), None)
        saved = {k.strip().lower(): v for k, v in (s.config or {}).get("pending_with_map", {}).items()}
        for v, n in (col.profile.get("values", []) if col else []):
            pw_values.append({"value": v, "count": n, "category": saved.get(v.strip().lower()) or ("wfx" if v.strip().lower() == "wfx" else None)})
    status_values = []  # every distinct value of a column mapped to a status-type field, and the category it will get
    if ent is not None:
        from app.modules.excel_intel.catalog import categorize_status
        saved = (s.config or {}).get("value_maps", {})
        for c in s.columns:
            f = ent.field(c.mapping.target_field) if c.mapping and c.mapping.target_field else None
            if f is not None and f.type == "status":
                for v, n in c.profile.get("values", []):
                    mine = saved.get(f.key, {}).get(" ".join(str(v).lower().split()))
                    status_values.append({"field": f.key, "header": c.header, "value": v, "count": n, "category": mine or categorize_status(str(v)), "chosen": mine is not None})
    return {
        "status_values": status_values,
        "pending_with_values": pw_values,
        "id": s.id, "name": s.name, "classification": s.classification, "classification_label": CLASS_LABEL.get(s.classification),
        "class_confidence": s.class_confidence, "entity": s.entity, "enabled": s.enabled, "config": s.config, "profile": s.profile,
        "entities": [{"key": e.key, "label": e.label} for e in ENTITIES.values()],
        "fields": [{"key": f.key, "label": f.label, "type": f.type, "required": f.required} for f in ent.fields] if ent else [],
        "layout": ent.layout if ent else None,
        "columns": [
            {"id": c.id, "index": c.index, "letter": c.letter, "header": c.header, "group_label": c.group_label,
             "inferred_type": c.inferred_type, "profile": c.profile,
             "mapping": None if c.mapping is None else {
                 "target_field": c.mapping.target_field, "score": c.mapping.score, "level": c.mapping.level,
                 "status": c.mapping.status, "source": c.mapping.source, "alternatives": c.mapping.alternatives}}
            for c in s.columns
        ],
    }


class SheetPatch(BaseModel):
    enabled: Optional[bool] = None
    entity: Optional[str] = None  # "" = no target
    header_row: Optional[int] = Field(None, ge=1, le=200)
    product_map: Optional[dict[str, Optional[str]]] = None
    value_maps: Optional[dict[str, dict[str, Optional[str]]]] = None
    gate_type: Optional[str] = Field(None, max_length=60)
    pending_with_map: Optional[dict[str, Optional[str]]] = None  # raw value -> customer | wfx | external | internal


@router.patch("/{batch_id}/sheets/{sheet_id}")
def patch_sheet(batch_id: uuid.UUID, sheet_id: uuid.UUID, body: SheetPatch, db: Session = Depends(get_db),
                user: User = Depends(require("imports:upload"))):
    b = _batch(db, user, batch_id)
    _editable(b)
    s = _sheet(b, sheet_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("entity") and data["entity"] not in ENTITIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown target entity")
    cfg = dict(s.config or {})
    if "product_map" in data:
        cfg["product_map"] = {**cfg.get("product_map", {}), **data["product_map"]}
    if "pending_with_map" in data:
        bad = [v for v in data["pending_with_map"].values() if v not in (None, "customer", "wfx", "external", "internal", "ignore")]
        if bad:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "pending_with values must be customer, wfx, external, internal or ignore")
        cfg["pending_with_map"] = {**cfg.get("pending_with_map", {}), **data["pending_with_map"]}
    if "value_maps" in data:
        valid = (None, "not_started", "in_progress", "done", "blocked", "cancelled")
        merged = {f: dict(m) for f, m in cfg.get("value_maps", {}).items()}
        for f, m in data["value_maps"].items():
            for raw, cat in m.items():
                if cat not in valid:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Status category must be one of {valid[1:]}")
                key = " ".join(raw.lower().split())
                if cat is None:
                    merged.get(f, {}).pop(key, None)
                else:
                    merged.setdefault(f, {})[key] = cat
        cfg["value_maps"] = merged
    if "gate_type" in data and data["gate_type"]:
        cfg["gate_type"] = data["gate_type"]
    s.config = cfg
    if "entity" in data or "header_row" in data:
        service.reprofile(db, b, s, data.get("header_row", cfg.get("header_row")), data.get("entity"))
    if "enabled" in data:
        s.enabled = bool(data["enabled"]) and bool(s.entity)
    write_audit(db, user, "import_sheet_edit", "import_batch", b.id, after={"sheet": s.name, **{k: v for k, v in data.items()}})
    db.commit()
    return {"ok": True}


class MappingItem(BaseModel):
    column_id: uuid.UUID
    target_field: Optional[str] = None
    ignore: bool = False


class MappingsBody(BaseModel):
    mappings: list[MappingItem]


@router.put("/{batch_id}/sheets/{sheet_id}/mappings")
def put_mappings(batch_id: uuid.UUID, sheet_id: uuid.UUID, body: MappingsBody, db: Session = Depends(get_db),
                 user: User = Depends(require("imports:upload"))):
    b = _batch(db, user, batch_id)
    _editable(b)
    s = _sheet(b, sheet_id)
    ent = ENTITIES.get(s.entity) if s.entity else None
    if ent is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a target type for this sheet first")
    cols = {c.id: c for c in s.columns}
    for it in body.mappings:
        c = cols.get(it.column_id)
        if c is None or c.mapping is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown column")
        if it.target_field and ent.field(it.target_field) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown field '{it.target_field}'")
    # a field may be used once, except planned/actual date in matrix product groups
    claimed: dict[str, uuid.UUID] = {}
    shared = ("planned_date", "actual_date") if ent.layout == "matrix" else ()
    changes = {it.column_id: it for it in body.mappings}
    for c in s.columns:
        it = changes.get(c.id)
        field = (it.target_field if it and not it.ignore else None) if it else (c.mapping.target_field if c.mapping.status != "ignored" else None)
        if field and field not in shared:
            if field in claimed:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Field '{ent.field(field).label}' is mapped to two columns ('{cols[claimed[field]].header}' and '{c.header}')")
            claimed[field] = c.id
    for it in body.mappings:
        m = cols[it.column_id].mapping
        if it.ignore or not it.target_field:
            m.target_field, m.status, m.source = None, "ignored", "user"
        else:
            if it.target_field != m.target_field:
                m.level, m.source = "manual", "user"
            m.target_field, m.status = it.target_field, "confirmed"
    write_audit(db, user, "import_mapping_edit", "import_batch", b.id, after={"sheet": s.name, "columns": len(body.mappings)})
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------- validate / errors / preview
@router.post("/{batch_id}/validate")
def validate(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:upload"))):
    b = _batch(db, user, batch_id)
    _editable(b)
    return service.run_validation(db, b)


@router.get("/{batch_id}/errors")
def errors(batch_id: uuid.UUID, sheet_id: Optional[uuid.UUID] = None, severity: Optional[str] = None, code: Optional[str] = None,
           page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
           db: Session = Depends(get_db), user: User = Depends(require("imports:read"))):
    b = _batch(db, user, batch_id)
    stmt = select(ValidationIssue).where(ValidationIssue.batch_id == b.id)
    if sheet_id:
        stmt = stmt.where(ValidationIssue.sheet_id == sheet_id)
    if severity:
        stmt = stmt.where(ValidationIssue.severity == severity)
    if code:
        stmt = stmt.where(ValidationIssue.code == code)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(ValidationIssue.row_number.is_(None).desc(), ValidationIssue.row_number, ValidationIssue.id)
                      .offset((page - 1) * size).limit(size)).all()
    names = {s.id: s.name for s in b.sheets}
    return {"items": [_issue_out(i, names) for i in rows], "total": total, "page": page, "size": size}


def _issue_out(i: ValidationIssue, names: dict) -> dict:
    return {"id": i.id, "sheet": names.get(i.sheet_id), "row": i.row_number, "column": i.column_header, "field": i.field,
            "severity": i.severity, "code": i.code, "message": i.message, "raw_value": i.raw_value, "rejects_row": i.rejects_row}


def _csv_safe(v: Any) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # spreadsheet formula injection


@router.get("/{batch_id}/errors.csv")
def errors_csv(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:read"))):
    b = _batch(db, user, batch_id)
    names = {s.id: s.name for s in b.sheets}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Sheet", "Row", "Column", "Field", "Severity", "Code", "Row rejected", "Message", "Original value"])
    for i in db.scalars(select(ValidationIssue).where(ValidationIssue.batch_id == b.id).order_by(ValidationIssue.sheet_id, ValidationIssue.row_number)):
        w.writerow([_csv_safe(x) for x in (names.get(i.sheet_id), i.row_number, i.column_header, i.field, i.severity, i.code,
                                           "yes" if i.rejects_row else "no", i.message, i.raw_value)])
    fname = "".join(ch for ch in b.filename.rsplit(".", 1)[0] if ch.isalnum() or ch in "-_ ")[:60] or "import"
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}-error-report.csv"'})


@router.get("/{batch_id}/preview")
def get_preview(batch_id: uuid.UUID, sheet_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:read"))):
    b = _batch(db, user, batch_id)
    s = _sheet(b, sheet_id)
    if not s.entity:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This sheet has no import target")
    return service.preview(db, b, s)


# ----------------------------------------------------------------- relationships / dashboards
@router.get("/{batch_id}/relationships")
def relationships(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:read"))):
    b = _batch(db, user, batch_id)
    return (b.meta or {}).get("relationships", {"candidates": [], "keys": [], "repeated_references": []})


class Decision(BaseModel):
    decision: str = Field(pattern="^(confirmed|rejected)$")


@router.patch("/{batch_id}/relationships/{index}")
def decide_relationship(batch_id: uuid.UUID, index: int, body: Decision, db: Session = Depends(get_db),
                        user: User = Depends(require("imports:upload"))):
    b = _batch(db, user, batch_id)
    meta = dict(b.meta or {})
    rel = meta.get("relationships", {})
    if not 0 <= index < len(rel.get("candidates", [])):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relationship not found")
    rel["candidates"][index]["decision"] = body.decision
    meta["relationships"] = rel
    b.meta = meta
    db.commit()
    return {"ok": True}


@router.get("/{batch_id}/dashboard-suggestions")
def suggestions(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:read"))):
    return service.dashboard_suggestions(_batch(db, user, batch_id))


# ----------------------------------------------------------------- commit / rollback
class CommitBody(BaseModel):
    project_id: uuid.UUID
    mode: str = "create_only"
    confirm_rejected: bool = False
    template_name: Optional[str] = Field(None, max_length=150)


@router.post("/{batch_id}/commit")
def commit(batch_id: uuid.UUID, body: CommitBody, db: Session = Depends(get_db), user: User = Depends(require("imports:commit"))):
    b = _batch(db, user, batch_id)
    ensure_project_access(db, user, body.project_id)
    try:
        return committer.commit(db, b, user, body.project_id, body.mode, body.confirm_rejected, body.template_name)
    except committer.CommitError as e:
        raise HTTPException(e.status, e.message)


@router.post("/{batch_id}/rollback")
def rollback(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:rollback"))):
    b = _batch(db, user, batch_id)
    try:
        return committer.rollback(db, b, user)
    except committer.CommitError as e:
        raise HTTPException(e.status, e.message)


# ----------------------------------------------------------------- templates
@templates_router.get("")
def list_templates(db: Session = Depends(get_db), _: User = Depends(require("imports:read"))):
    return [{"id": t.id, "name": t.name, "created_at": t.created_at, "sheets": [s["name"] for s in t.definition.get("sheets", [])]}
            for t in db.scalars(select(MappingTemplate).order_by(MappingTemplate.name))]


@templates_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("imports:commit"))):
    t = db.get(MappingTemplate, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    write_audit(db, user, "delete", "mapping_template", t.id, before={"name": t.name})
    for b in db.scalars(select(ImportBatch).where(ImportBatch.template_id == t.id)):
        b.template_id = None
    db.delete(t)
    db.commit()
