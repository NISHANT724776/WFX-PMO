"""Orchestration: analyse an uploaded workbook, rebuild/edit mappings, validate, preview, templates."""
import logging
import uuid
from collections import Counter
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import get_storage
from app.db.session import SessionLocal
from app.models import (
    ColumnMapping,
    DetectedColumn,
    ImportBatch,
    Location,
    MappingTemplate,
    Product,
    UploadedSheet,
    ValidationIssue,
)
from app.modules.excel_intel import recommender, relations
from app.modules.excel_intel.catalog import CLASS_ENTITY, ENTITIES, NOT_YET
from app.modules.excel_intel.classifier import classify_sheet
from app.modules.excel_intel.mapper import suggest_mappings
from app.modules.excel_intel.profiler import SheetProfile, norm_header, profile_sheet
from app.modules.excel_intel.reader import SheetGrid, read_workbook
from app.modules.excel_intel.transform import EXCLUDE, SheetResult, norm, process_sheet, slug

log = logging.getLogger(__name__)
MAX_STORED_ISSUES = 5000


# ---------------------------------------------------------------- helpers
def load_grids(batch: ImportBatch) -> dict[str, SheetGrid]:
    path = get_storage().path(batch.stored_name)
    return {g.name: g for g in read_workbook(path, batch.ext)}


def _history(db: Session) -> dict[str, str]:
    """header (normalised) -> field most often confirmed by users before."""
    rows = db.execute(
        select(DetectedColumn.header, ColumnMapping.target_field)
        .join(ColumnMapping, ColumnMapping.column_id == DetectedColumn.id)
        .where(ColumnMapping.status == "confirmed", ColumnMapping.target_field.is_not(None))
        .limit(5000)
    ).all()
    counts: dict[str, Counter] = {}
    for h, f in rows:
        counts.setdefault(norm_header(h), Counter())[f] += 1
    return {h: c.most_common(1)[0][0] for h, c in counts.items()}


def match_template(templates: list[MappingTemplate], profile: SheetProfile) -> tuple[dict | None, MappingTemplate | None]:
    heads = {norm_header(c.header) for c in profile.columns}
    best, best_t, best_s = None, None, 0.0
    for t in templates:
        for sd in t.definition.get("sheets", []):
            th = set(sd["headers"])
            if not th or not heads:
                continue
            j = len(th & heads) / len(th | heads)
            if j >= 0.8 and j > best_s:
                best, best_t, best_s = sd, t, j
    return best, best_t


def _suggest_products(labels: list[str], products: list[Product]) -> dict[str, str | None]:
    idx = {}
    for p in products:
        idx[norm(p.code)] = str(p.id)
        idx[norm(p.name)] = str(p.id)
    return {lab: idx.get(norm(lab)) for lab in labels}


def populate_sheet(
    db: Session, sheet: UploadedSheet, profile: SheetProfile, history: dict[str, str],
    template_map: dict[str, str] | None, products: list[Product],
) -> None:
    for c in list(sheet.columns):
        db.delete(c)
    sheet.columns = []
    db.flush()
    entity = ENTITIES.get(sheet.entity) if sheet.entity else None
    sugg = {s.column_index: s for s in suggest_mappings(profile.columns, entity, 1.0, history, template_map)} if entity else {}
    for c in profile.columns:
        dc = DetectedColumn(index=c.index, letter=c.letter, header=c.header, group_label=c.group_label,
                            inferred_type=c.inferred_type, profile=jsonable_encoder(c.profile))
        s = sugg.get(c.index)
        if s:
            dc.mapping = ColumnMapping(
                sheet_id=sheet.id, target_field=s.target_field, score=s.score, level=s.level, source=s.source,
                status="suggested" if s.target_field else "unmapped",
                alternatives=[[k, v] for k, v in s.alternatives],
            )
        sheet.columns.append(dc)
    groups = sorted({c.group_label for c in profile.columns if c.group_label})
    cfg = dict(sheet.config or {})
    if groups:
        existing = cfg.get("product_map", {})
        sug = _suggest_products(groups, products)
        cfg["product_map"] = {g: existing.get(g) or sug.get(g) for g in groups}
        cfg["product_suggested"] = {g: bool(sug.get(g)) for g in groups}
    cfg["header_row"] = profile.header_row
    sheet.config = cfg
    sheet.profile = jsonable_encoder({
        "header_row": profile.header_row, "header_candidates": profile.header_candidates, "group_row": profile.group_row,
        "data_start": profile.data_start, "data_end": profile.data_end,
        "section_rows": {"count": len(profile.section_rows), "examples": list(profile.section_rows.values())[:20]},
        "stats": profile.stats,
        **{k: (sheet.profile or {}).get(k) for k in ("template", "not_yet")},
    })
    sheet.n_rows = profile.stats["data_rows"]
    sheet.n_cols = len(profile.columns)


def analyze_batch(batch_id: uuid.UUID) -> None:
    """Runs in the background (FastAPI BackgroundTasks now; the same function is the Celery task body later)."""
    with SessionLocal() as db:
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            return
        batch.status = "analyzing"
        db.commit()
        try:
            grids = list(load_grids(batch).values())
            history = _history(db)
            templates = list(db.scalars(select(MappingTemplate)))
            products = list(db.scalars(select(Product)))
            hits: Counter = Counter()
            rel_input = []
            for pos, grid in enumerate(grids):
                profile = profile_sheet(grid)
                cls, conf = classify_sheet(grid.name, profile)
                tdef, tmpl = match_template(templates, profile)
                entity = CLASS_ENTITY[cls]
                cfg: dict[str, Any] = {}
                template_map = None
                if tdef:
                    if tdef.get("header_row") and tdef["header_row"] != profile.header_row:
                        profile = profile_sheet(grid, tdef["header_row"])
                    entity, template_map = tdef["entity"], tdef["mappings"]
                    cfg = {k: tdef[k] for k in ("gate_type", "value_maps", "product_map") if k in tdef}
                    hits[tmpl.id] += 1
                if entity == "approval_gate":
                    cfg.setdefault("gate_type", slug(grid.name))
                sheet = UploadedSheet(
                    batch_id=batch.id, name=grid.name, position=pos, state=grid.state,
                    classification=cls, class_confidence=conf, entity=entity, config=cfg,
                    enabled=bool(entity) and profile.stats["data_rows"] > 0 and grid.state == "visible",
                )
                sheet.profile = {"template": tmpl.name if tdef else None, "not_yet": NOT_YET.get(cls)}
                db.add(sheet)
                db.flush()
                populate_sheet(db, sheet, profile, history, template_map, products)
                if profile.columns:
                    rel_input.append({
                        "id": str(sheet.id), "name": grid.name, "columns": profile.columns,
                        "values": {c.index: relations.column_values(grid.rows, profile.data_rows, c.index) for c in profile.columns
                                   if c.inferred_type in ("id", "text", "number")},
                    })
            batch.meta = {"relationships": relations.detect(rel_input), "sheet_count": len(grids)}
            if hits:
                batch.template_id = hits.most_common(1)[0][0]
            batch.status = "ready"
            db.commit()
        except Exception as e:  # noqa: BLE001 - report to the user, keep the batch for diagnosis
            log.exception("analysis failed for batch %s", batch_id)
            db.rollback()
            batch = db.get(ImportBatch, batch_id)
            batch.status, batch.error = "failed", f"Could not analyse workbook ({type(e).__name__}). Check that the file opens in Excel."
            db.commit()


def reprofile(db: Session, batch: ImportBatch, sheet: UploadedSheet, header_row: int | None, entity: str | None) -> None:
    """After the user changes header row or target entity: rebuild columns and suggestions for that sheet."""
    grid = load_grids(batch)[sheet.name]
    if entity is not None:
        sheet.entity = entity or None
    profile = profile_sheet(grid, header_row)
    sheet.config = {**(sheet.config or {})}
    if sheet.entity == "approval_gate":
        sheet.config.setdefault("gate_type", slug(sheet.name))
    populate_sheet(db, sheet, profile, _history(db), None, list(db.scalars(select(Product))))
    sheet.enabled = bool(sheet.entity) and profile.stats["data_rows"] > 0


def effective_mappings(sheet: UploadedSheet) -> tuple[dict[int, str], int]:
    """Approved mappings only: confirmed, or high-confidence suggestions. Medium needs a click; low never auto-applies."""
    eff, unconfirmed = {}, 0
    for c in sheet.columns:
        m = c.mapping
        if not m or not m.target_field or m.status in ("ignored", "unmapped"):
            continue
        if m.status == "confirmed" or (m.status == "suggested" and m.level == "high"):
            eff[c.index] = m.target_field
        elif m.status == "suggested" and m.level == "medium":
            unconfirmed += 1
    return eff, unconfirmed


def build_ctx(db: Session, sheet: UploadedSheet, unconfirmed: int) -> dict:
    loc = {}
    for l in db.scalars(select(Location)):
        loc[norm(l.name)] = str(l.id)
        loc[norm(l.code)] = str(l.id)
    return {
        "product_map": (sheet.config or {}).get("product_map", {}),
        "location_lookup": loc,
        "gate_type": (sheet.config or {}).get("gate_type", slug(sheet.name)),
        "unconfirmed": unconfirmed,
    }


def process(db: Session, sheet: UploadedSheet, grid: SheetGrid) -> tuple[SheetResult, SheetProfile]:
    profile = profile_sheet(grid, (sheet.config or {}).get("header_row"))
    eff, unconfirmed = effective_mappings(sheet)
    res = process_sheet(grid, profile, profile.columns, eff, ENTITIES[sheet.entity], sheet.config or {}, build_ctx(db, sheet, unconfirmed))
    return res, profile


def run_validation(db: Session, batch: ImportBatch) -> dict:
    grids = load_grids(batch)
    db.query(ValidationIssue).filter(ValidationIssue.batch_id == batch.id).delete()
    summaries = []
    for sheet in batch.sheets:
        if not sheet.enabled or not sheet.entity:
            summaries.append({"sheet_id": str(sheet.id), "name": sheet.name, "skipped": True,
                              "reason": (f"Import for this sheet type arrives in {sheet.profile['not_yet']}" if (sheet.profile or {}).get("not_yet") else "Sheet not enabled")})
            continue
        res, profile = process(db, sheet, grids[sheet.name])
        rejected = res.rejected_rows
        sev = Counter(i.severity for i in res.issues)
        stored = res.issues[:MAX_STORED_ISSUES]
        for i in stored:
            db.add(ValidationIssue(batch_id=batch.id, sheet_id=sheet.id, row_number=i.row, column_header=i.header, field=i.field,
                                   severity=i.severity, code=i.code, message=i.message, raw_value=i.raw, rejects_row=i.rejects))
        if len(res.issues) > len(stored):
            db.add(ValidationIssue(batch_id=batch.id, sheet_id=sheet.id, severity="info", code="issues_truncated",
                                   message=f"{len(res.issues) - len(stored)} further issues not stored"))
        source_rows = {r.source_row for r in res.rows}
        summaries.append({
            "sheet_id": str(sheet.id), "name": sheet.name, "entity": sheet.entity, "skipped": False,
            "source_rows": len(profile.data_rows), "records": len(res.rows),
            "importable": len([r for r in res.rows if r.source_row not in rejected]),
            "rejected_rows": len(rejected), "empty_rows": res.empty_rows, "section_rows": res.section_rows,
            "errors": sev["error"], "warnings": sev["warning"], "infos": sev["info"],
            "blocking": [{"code": i.code, "message": i.message} for i in res.blocking],
        })
    meta = dict(batch.meta or {})
    meta["validation"] = summaries
    batch.meta = meta
    db.commit()
    return {"sheets": summaries, "can_commit": all(not s.get("blocking") for s in summaries if not s.get("skipped"))
            and any(not s.get("skipped") for s in summaries)}


def preview(db: Session, batch: ImportBatch, sheet: UploadedSheet, limit: int = 25) -> dict:
    res, profile = process(db, sheet, load_grids(batch)[sheet.name])
    rejected = res.rejected_rows
    ent = ENTITIES[sheet.entity]
    fields = [f for f in ent.fields if any(f.key in r.values for r in res.rows[:200])]
    if sheet.entity == "tracker_event":
        fields = [ent.field("event_name"), ent.field("responsibility"), ent.field("spoc")] + [ent.field("planned_date"), ent.field("actual_date")]
    rows = []
    for r in res.rows[:limit]:
        rows.append({"source_row": r.source_row, "rejected": r.source_row in rejected,
                     "product": r.values.get("product_label"), "values": jsonable_encoder({f.key: r.values.get(f.key) for f in fields})})
    return {
        "fields": [{"key": f.key, "label": f.label} for f in fields], "rows": rows,
        "counts": {"records": len(res.rows), "importable": len([r for r in res.rows if r.source_row not in rejected]),
                   "rejected_rows": len(rejected), "empty_rows": res.empty_rows, "section_rows": res.section_rows},
        "blocking": [{"code": i.code, "message": i.message} for i in res.blocking],
    }


# ---------------------------------------------------------------- templates
def save_template(db: Session, batch: ImportBatch, name: str, user_id: uuid.UUID) -> MappingTemplate:
    sheets = []
    for sheet in batch.sheets:
        if not sheet.enabled or not sheet.entity:
            continue
        eff, _ = effective_mappings(sheet)
        by_idx = {c.index: c for c in sheet.columns}
        sheets.append({
            "name": sheet.name, "entity": sheet.entity, "header_row": (sheet.config or {}).get("header_row"),
            "headers": sorted({norm_header(c.header) for c in sheet.columns}),
            "mappings": {norm_header(by_idx[i].header): f for i, f in eff.items() if i in by_idx},
            **{k: (sheet.config or {})[k] for k in ("gate_type", "value_maps", "product_map") if k in (sheet.config or {})},
        })
    t = db.scalar(select(MappingTemplate).where(MappingTemplate.name == name))
    if t is None:
        t = MappingTemplate(name=name, created_by=user_id, customer_id=None, definition={"sheets": sheets})
        db.add(t)
    else:
        t.definition = {"sheets": sheets}
    db.flush()
    return t


def dashboard_suggestions(batch: ImportBatch) -> list[dict]:
    mapped: dict[str, set[str]] = {}
    for sheet in batch.sheets:
        if sheet.enabled and sheet.entity:
            eff, _ = effective_mappings(sheet)
            mapped.setdefault(sheet.entity, set()).update(eff.values())
    return recommender.suggest(mapped)
