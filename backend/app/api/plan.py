"""Project plan: tasks/milestones, date revisions, dependencies, phase->product assignment."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session

from app.core.lifecycle import move
from app.core.audit import row_to_dict, write_audit
from app.core.deps import ensure_project_access, get_db, require
from app.models import Location, Product, Project, ProjectPhase, StatusConfig, User
from app.models.canonical import (
    BrdRequirement, DateRevision, DeliveryItem, DependencyItem, GapSpecification, WorkItem, WorkItemDependency,
)
from app.models.workspace import IntegrationItem, ReportItem
from app.modules.planning.delays import assess
from app.modules.planning.graph import analyse, current_range

router = APIRouter()
HIDE = {"raw_values", "match_key"}
ENTITY_FIELDS = {  # entity -> field -> (baseline column, revised column)
    "work_item": {"planned_start": ("planned_start", "revised_start"), "planned_finish": ("planned_finish", "revised_finish")},
    "dependency_item": {"target_date": ("original_target_date", "revised_target_date")},
    "delivery_item": {"delivery_target_date": ("delivery_target_date", "revised_target_date")},
    "gap_specification": {"target_date": ("target_date", "revised_target_date")},
    "brd_requirement": {"target_date": ("target_date", "revised_target_date")},
    "integration_item": {"target_date": ("target_date", "revised_target_date")},
    "report_item": {"target_date": ("target_date", "revised_target_date")},
}


def norm(s: Any) -> str:
    return " ".join(str(s or "").split()).lower()


def project_or_404(db: Session, user: User, pid: uuid.UUID) -> Project:
    ensure_project_access(db, user, pid)
    p = db.get(Project, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


def wi_or_404(db: Session, pid: uuid.UUID, wid: uuid.UUID) -> WorkItem:
    w = db.get(WorkItem, wid)
    if w is None or w.project_id != pid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work item not found")
    return w


def wi_out(w: WorkItem, project: Project, as_of: date, phases: dict[uuid.UUID, str] | None = None) -> dict:
    d = {c.key: getattr(w, c.key) for c in inspect(w).mapper.column_attrs if c.key not in HIDE}
    a = assess(w.planned_start, w.planned_finish, w.revised_start, w.revised_finish, w.status_category,
               w.actual_start, w.actual_finish, as_of, project.delay_grace_days or 0)
    d.update(effective_start=a.effective_start, effective_finish=a.effective_finish, is_overdue=a.overdue,
             is_start_delayed=a.start_delayed, days_late=a.days_late, slippage_days=a.slippage_days, is_closed=a.closed,
             phase_name=(phases or {}).get(w.phase_id),
             percent_mismatch=w.percent_complete is not None and ((w.percent_complete < 100 and a.closed) or (w.percent_complete == 100 and not a.closed)))
    return jsonable_encoder(d)


def _status(db: Session, entity: str, code: str) -> StatusConfig:
    sc = db.scalar(select(StatusConfig).where(StatusConfig.entity_type == entity, StatusConfig.code == code))
    if sc is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown status '{code}' for {entity}")
    return sc


def _check_refs(db: Session, project: Project, data: dict) -> None:
    if data.get("phase_id"):
        ph = db.get(ProjectPhase, data["phase_id"])
        if ph is None or ph.project_id != project.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Phase does not belong to this project")
    if data.get("product_id") and db.get(Product, data["product_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown product")
    if data.get("location_id") and db.get(Location, data["location_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown location")
    if data.get("parent_id"):
        par = db.get(WorkItem, data["parent_id"])
        if par is None or par.project_id != project.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Parent does not belong to this project")


# ------------------------------------------------------------------ list / read
@router.get("/{project_id}/work-items")
def list_work_items(
    project_id: uuid.UUID, q: str | None = None, status_category: str | None = None, phase_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None, include_unassigned: bool = True, kind: str | None = None,
    overdue: bool | None = None, due_from: date | None = None, due_to: date | None = None, as_of: date | None = None,
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(require("projects:read")),
):
    project = project_or_404(db, user, project_id)
    as_of = as_of or date.today()
    stmt = select(WorkItem).where(WorkItem.project_id == project_id)
    if q:
        stmt = stmt.where(WorkItem.title.ilike(f"%{q}%"))
    if status_category:
        stmt = stmt.where(WorkItem.status_category == status_category)
    if phase_id:
        stmt = stmt.where(WorkItem.phase_id == phase_id)
    if kind:
        stmt = stmt.where(WorkItem.kind == kind)
    if product_id:  # product view = tasks tagged with it, plus (optionally) project-wide tasks
        cond = WorkItem.product_id == product_id
        stmt = stmt.where(or_(cond, WorkItem.product_id.is_(None)) if include_unassigned else cond)
    if due_from or due_to:  # effective finish in range
        eff = func.coalesce(WorkItem.revised_finish, WorkItem.planned_finish)
        if due_from:
            stmt = stmt.where(eff >= due_from)
        if due_to:
            stmt = stmt.where(eff <= due_to)
    rows = db.scalars(stmt.order_by(WorkItem.sort_order, WorkItem.id)).all()
    phases = {p.id: p.name for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id))}
    items = [wi_out(w, project, as_of, phases) for w in rows]
    _, nodes = analyse(rows, db.scalars(select(WorkItemDependency).where(WorkItemDependency.project_id == project_id)).all(), as_of, project.delay_grace_days or 0)
    proposed = set(db.scalars(select(DateRevision.entity_id).where(DateRevision.project_id == project_id, DateRevision.entity_type == "work_item", DateRevision.status == "proposed")))
    for i, w in zip(items, rows):
        i.update(is_critical_milestone=nodes[w.id]["critical_milestone"], blocked_by_late=nodes[w.id]["blocked_by_late"], has_pending_revision=w.id in proposed)
    if overdue is not None:  # derived flag: filtered after computing (plans are hundreds of rows)
        items = [i for i in items if (i["is_overdue"] or i["is_start_delayed"]) == overdue]
    total = len(items)
    return {"items": items[(page - 1) * size : page * size], "total": total, "page": page, "size": size,
            "as_of": as_of.isoformat(), "grace_days": project.delay_grace_days or 0}


@router.get("/{project_id}/work-items/{wid}")
def get_work_item(project_id: uuid.UUID, wid: uuid.UUID, as_of: date | None = None, db: Session = Depends(get_db),
                  user: User = Depends(require("projects:read"))):
    project = project_or_404(db, user, project_id)
    w = wi_or_404(db, project_id, wid)
    phases = {p.id: p.name for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id))}
    names = {i.id: i.title for i in db.scalars(select(WorkItem).where(WorkItem.project_id == project_id))}
    deps = db.scalars(select(WorkItemDependency).where(or_(WorkItemDependency.successor_id == wid, WorkItemDependency.predecessor_id == wid))).all()
    out = wi_out(w, project, as_of or date.today(), phases)
    out["predecessors"] = [{"id": d.id, "work_item_id": d.predecessor_id, "title": names.get(d.predecessor_id), "type": d.dep_type, "lag_days": d.lag_days}
                           for d in deps if d.successor_id == wid]
    out["successors"] = [{"id": d.id, "work_item_id": d.successor_id, "title": names.get(d.successor_id), "type": d.dep_type, "lag_days": d.lag_days}
                         for d in deps if d.predecessor_id == wid]
    out["revisions"] = revisions_out(db, "work_item", wid)
    return out


# ------------------------------------------------------------------ create / edit / delete
class WorkItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    kind: str = Field("task", pattern="^(task|milestone)$")
    phase_id: Optional[uuid.UUID] = None
    parent_id: Optional[uuid.UUID] = None
    product_id: Optional[uuid.UUID] = None
    responsible_party: Optional[str] = Field(None, max_length=100)
    owner_name: Optional[str] = Field(None, max_length=150)
    location_label: Optional[str] = Field(None, max_length=200)
    location_id: Optional[uuid.UUID] = None
    delivery_mode: Optional[str] = Field(None, pattern="^(onsite|online)$")
    planned_start: Optional[date] = None
    planned_finish: Optional[date] = None
    status: str = "not_started"
    remarks: Optional[str] = None
    resource_allocation: Optional[str] = Field(None, max_length=100)
    dependencies_text: Optional[str] = None


class WorkItemPatch(BaseModel):
    """planned_start/planned_finish are deliberately absent: the baseline is changed only through a date revision."""

    title: Optional[str] = Field(None, min_length=1, max_length=1000)
    kind: Optional[str] = Field(None, pattern="^(task|milestone)$")
    phase_id: Optional[uuid.UUID] = None
    parent_id: Optional[uuid.UUID] = None
    product_id: Optional[uuid.UUID] = None
    responsible_party: Optional[str] = Field(None, max_length=100)
    owner_name: Optional[str] = Field(None, max_length=150)
    location_label: Optional[str] = Field(None, max_length=200)
    location_id: Optional[uuid.UUID] = None
    delivery_mode: Optional[str] = Field(None, pattern="^(onsite|online)$")
    actual_start: Optional[date] = None
    actual_finish: Optional[date] = None
    percent_complete: Optional[int] = Field(None, ge=0, le=100)
    status: Optional[str] = None
    remarks: Optional[str] = None
    resource_allocation: Optional[str] = Field(None, max_length=100)
    dependencies_text: Optional[str] = None
    model_config = {"extra": "forbid"}


def _apply_status_generic(db: Session, obj: Any, entity: str, code: str) -> None:
    sc = _status(db, entity, code)
    obj.status_raw, obj.status_category = sc.label, sc.category


def _apply_status(db: Session, w: WorkItem, code: str) -> None:
    _apply_status_generic(db, w, "work_item", code)


@router.post("/{project_id}/work-items", status_code=status.HTTP_201_CREATED)
def create_work_item(project_id: uuid.UUID, body: WorkItemCreate, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project = project_or_404(db, user, project_id)
    data = body.model_dump()
    if data["planned_start"] and data["planned_finish"] and data["planned_finish"] < data["planned_start"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "planned_finish is before planned_start")
    _check_refs(db, project, data)
    code = data.pop("status")
    last = db.scalar(select(func.max(WorkItem.sort_order)).where(WorkItem.project_id == project_id)) or 0
    w = WorkItem(project_id=project_id, match_key="", sort_order=last + 1, **data)
    _apply_status(db, w, code)
    db.add(w)
    db.flush()
    write_audit(db, user, "create", "work_item", w.id, after=row_to_dict(w))
    db.commit()
    return wi_out(w, project, date.today())


@router.patch("/{project_id}/work-items/{wid}")
def patch_work_item(project_id: uuid.UUID, wid: uuid.UUID, body: WorkItemPatch, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project = project_or_404(db, user, project_id)
    w = wi_or_404(db, project_id, wid)
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, project, data)
    if data.get("parent_id") == wid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "An item cannot be its own parent")
    before = row_to_dict(w)
    code = data.pop("status", None)
    for k, v in data.items():
        setattr(w, k, v)
    if code:
        _apply_status(db, w, code)
    if w.actual_start and w.actual_finish and w.actual_finish < w.actual_start:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "actual_finish is before actual_start")
    write_audit(db, user, "update", "work_item", w.id, before=before, after=row_to_dict(w))
    db.commit()
    return wi_out(w, project, date.today())


@router.delete("/{project_id}/work-items/{wid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work_item(project_id: uuid.UUID, wid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    w = wi_or_404(db, project_id, wid)
    move(db, user, "work_item", w, "delete")  # to the trash, with its sub-tasks; restorable
    db.commit()


# ------------------------------------------------------------------ date revisions (shared by work items and pending items)
def revisions_out(db: Session, entity: str, eid: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(DateRevision).where(DateRevision.entity_type == entity, DateRevision.entity_id == eid).order_by(DateRevision.requested_at, DateRevision.id)).all()
    return [_rev_out(r) for r in rows]


def _rev_out(r: DateRevision) -> dict:
    return jsonable_encoder({c.key: getattr(r, c.key) for c in inspect(r).mapper.column_attrs if c.key not in ("requested_by", "decided_by")})


class RevisionIn(BaseModel):
    field: str
    new_date: date
    reason: str = Field(min_length=3, max_length=1000)
    approve: bool = False


def current_date(obj: Any, entity: str, field: str) -> date | None:
    base, rev = ENTITY_FIELDS[entity][field]
    return getattr(obj, rev) or getattr(obj, base)


def create_revision(db: Session, user: User, project: Project, entity: str, obj: Any, body: RevisionIn) -> DateRevision:
    if body.field not in ENTITY_FIELDS[entity]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"field must be one of {sorted(ENTITY_FIELDS[entity])}")
    if body.approve and "plan:approve" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: plan:approve")
    old = current_date(obj, entity, body.field)
    if old == body.new_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "New date equals the current date")
    rev = DateRevision(project_id=project.id, entity_type=entity, entity_id=obj.id, field=body.field, old_date=old, new_date=body.new_date,
                       reason=body.reason.strip(), status="proposed", requested_by=user.id, requested_by_email=user.email)
    db.add(rev)
    db.flush()
    write_audit(db, user, "create", "date_revision", rev.id, after=row_to_dict(rev))
    if body.approve:
        decide(db, user, entity, obj, rev, True)
    return rev


def decide(db: Session, user: User, entity: str, obj: Any, rev: DateRevision, approve: bool) -> None:
    if rev.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Revision is already {rev.status}")
    if approve:
        _, revcol = ENTITY_FIELDS[entity][rev.field]
        if entity == "work_item":  # keep the resulting range sane
            s = rev.new_date if rev.field == "planned_start" else (obj.revised_start or obj.planned_start)
            f = rev.new_date if rev.field == "planned_finish" else (obj.revised_finish or obj.planned_finish)
            if s and f and f < s:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That date would put the finish before the start")
        setattr(obj, revcol, rev.new_date)
    rev.status = "approved" if approve else "rejected"
    rev.decided_by, rev.decided_by_email, rev.decided_at = user.id, user.email, datetime.now(timezone.utc)
    write_audit(db, user, "approve_revision" if approve else "reject_revision", "date_revision", rev.id, after={"status": rev.status, "new_date": str(rev.new_date)})


@router.post("/{project_id}/work-items/{wid}/revisions", status_code=status.HTTP_201_CREATED)
def add_revision(project_id: uuid.UUID, wid: uuid.UUID, body: RevisionIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project = project_or_404(db, user, project_id)
    w = wi_or_404(db, project_id, wid)
    create_revision(db, user, project, "work_item", w, body)
    db.commit()
    return revisions_out(db, "work_item", wid)


class Decision(BaseModel):
    approve: bool


@router.post("/{project_id}/revisions/{rid}/decision")
def decide_revision(project_id: uuid.UUID, rid: uuid.UUID, body: Decision, db: Session = Depends(get_db), user: User = Depends(require("plan:approve"))):
    project_or_404(db, user, project_id)
    rev = db.get(DateRevision, rid)
    if rev is None or rev.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    model = {"work_item": WorkItem, "dependency_item": DependencyItem, "delivery_item": DeliveryItem, "gap_specification": GapSpecification, "brd_requirement": BrdRequirement,
             "integration_item": IntegrationItem, "report_item": ReportItem}.get(rev.entity_type)
    obj = db.get(model, rev.entity_id) if model else None
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record no longer exists")
    decide(db, user, rev.entity_type, obj, rev, body.approve)
    db.commit()
    return revisions_out(db, rev.entity_type, rev.entity_id)


@router.get("/{project_id}/revisions")
def list_revisions(project_id: uuid.UUID, status_: str | None = Query(None, alias="status"), db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project_or_404(db, user, project_id)
    stmt = select(DateRevision).where(DateRevision.project_id == project_id)
    if status_:
        stmt = stmt.where(DateRevision.status == status_)
    return [_rev_out(r) for r in db.scalars(stmt.order_by(DateRevision.requested_at.desc()).limit(200)).all()]


# ------------------------------------------------------------------ dependencies
class DepIn(BaseModel):
    predecessor_id: uuid.UUID
    lag_days: int = Field(0, ge=-365, le=365)


def _reaches(db: Session, start: uuid.UUID, target: uuid.UUID) -> bool:
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur == target:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(db.scalars(select(WorkItemDependency.successor_id).where(WorkItemDependency.predecessor_id == cur)))
    return False


def add_dep(db: Session, user: User, project_id: uuid.UUID, pred: uuid.UUID, succ: uuid.UUID, lag: int = 0) -> WorkItemDependency:
    if pred == succ:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "An item cannot depend on itself")
    wi_or_404(db, project_id, pred)
    wi_or_404(db, project_id, succ)
    if db.scalar(select(WorkItemDependency.id).where(WorkItemDependency.predecessor_id == pred, WorkItemDependency.successor_id == succ)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Dependency already exists")
    if _reaches(db, succ, pred):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That dependency would create a loop")
    d = WorkItemDependency(project_id=project_id, predecessor_id=pred, successor_id=succ, lag_days=lag)
    db.add(d)
    db.flush()
    write_audit(db, user, "create", "work_item_dependency", d.id, after=row_to_dict(d))
    return d


@router.post("/{project_id}/work-items/{wid}/dependencies", status_code=status.HTTP_201_CREATED)
def add_dependency(project_id: uuid.UUID, wid: uuid.UUID, body: DepIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    add_dep(db, user, project_id, body.predecessor_id, wid, body.lag_days)
    pred, succ = wi_or_404(db, project_id, body.predecessor_id), wi_or_404(db, project_id, wid)
    pf, ss = current_range(pred)[1], current_range(succ)[0]
    warnings = []
    if pf and ss and (ss - pf).days - body.lag_days < 0:
        warnings.append(f"'{succ.title}' starts {(pf - ss).days + body.lag_days} day(s) before '{pred.title}' finishes; adjust one of the dates")
    db.commit()
    return {"ok": True, "warnings": warnings}


@router.delete("/{project_id}/dependencies/{dep_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_dependency(project_id: uuid.UUID, dep_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    d = db.get(WorkItemDependency, dep_id)
    if d is None or d.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dependency not found")
    write_audit(db, user, "delete", "work_item_dependency", d.id, before=row_to_dict(d))
    db.delete(d)
    db.commit()


@router.get("/{project_id}/dependencies")
def list_dependencies(project_id: uuid.UUID, as_of: date | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project_or_404(db, user, project_id)
    project = project_or_404(db, user, project_id)
    items = db.scalars(select(WorkItem).where(WorkItem.project_id == project_id)).all()  # archived/trashed tasks drop out of the chart
    deps = [d for d in db.scalars(select(WorkItemDependency).where(WorkItemDependency.project_id == project_id)) if d.predecessor_id in {i.id for i in items} and d.successor_id in {i.id for i in items}]
    links, _ = analyse(items, deps, as_of or date.today(), project.delay_grace_days or 0)
    return [{"id": d.id, "predecessor_id": d.predecessor_id, "successor_id": d.successor_id, "type": d.dep_type, "lag_days": d.lag_days, **links[d.id]} for d in deps]


@router.get("/{project_id}/dependency-suggestions")
def dependency_suggestions(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    """The plan's free-text 'Dependencies' column, matched to tasks ONLY on an exact title. Suggestions, never applied automatically."""
    project_or_404(db, user, project_id)
    items = db.scalars(select(WorkItem).where(WorkItem.project_id == project_id)).all()
    by_title: dict[str, list[WorkItem]] = {}
    for i in items:
        by_title.setdefault(norm(i.title), []).append(i)
    phases = {norm(p.name) for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id))}
    linked = {(d.predecessor_id, d.successor_id) for d in db.scalars(select(WorkItemDependency).where(WorkItemDependency.project_id == project_id))}
    out = []
    for i in items:
        if not i.dependencies_text:
            continue
        text = i.dependencies_text
        parts = [text] + ([p for p in text.replace("\n", ";").split(";") if p.strip()] if (";" in text or "\n" in text) else [])
        matches, phase_refs, seen = [], [], set()
        for part in parts:
            key = norm(part)
            for m in by_title.get(key, []):
                if m.id != i.id and m.id not in seen and (m.id, i.id) not in linked:
                    seen.add(m.id)
                    matches.append({"id": m.id, "title": m.title})
            if key in phases and part.strip() not in phase_refs:
                phase_refs.append(part.strip())
        out.append({"work_item_id": i.id, "title": i.title, "text": text, "matches": matches, "phase_refs": phase_refs,
                    "unambiguous": len(matches) == 1 and len(by_title[norm(matches[0]["title"])]) == 1})
    return out


class BulkDeps(BaseModel):
    pairs: list[dict[str, uuid.UUID]]


@router.post("/{project_id}/dependencies/bulk")
def bulk_dependencies(project_id: uuid.UUID, body: BulkDeps, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    created, skipped = 0, []
    for pair in body.pairs:
        try:
            add_dep(db, user, project_id, pair["predecessor_id"], pair["successor_id"])
            created += 1
        except HTTPException as e:
            skipped.append({"predecessor_id": str(pair["predecessor_id"]), "successor_id": str(pair["successor_id"]), "reason": e.detail})
    db.commit()
    return {"created": created, "skipped": skipped}


# ------------------------------------------------------------------ phase -> product (explicit user action)
class AssignProduct(BaseModel):
    product_id: Optional[uuid.UUID] = None


@router.post("/{project_id}/phases/{phase_id}/assign-product")
def assign_phase_product(project_id: uuid.UUID, phase_id: uuid.UUID, body: AssignProduct, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    """Tags every task of a phase with a product (or clears it). Plans carry no product column, so this is a deliberate choice."""
    project_or_404(db, user, project_id)
    ph = db.get(ProjectPhase, phase_id)
    if ph is None or ph.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase not found")
    if body.product_id and db.get(Product, body.product_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown product")
    items = db.scalars(select(WorkItem).where(WorkItem.phase_id == phase_id)).all()
    for w in items:
        w.product_id = body.product_id
    write_audit(db, user, "update", "project_phase", phase_id, after={"assign_product": str(body.product_id) if body.product_id else None, "tasks": len(items)})
    db.commit()
    return {"updated": len(items)}


# ------------------------------------------------------------------ reschedule (drag / resize on the Gantt)
class RescheduleIn(BaseModel):
    start: Optional[date] = None
    finish: Optional[date] = None
    reason: str = Field(min_length=3, max_length=1000)
    approve: bool = False


@router.post("/{project_id}/work-items/{wid}/reschedule")
def reschedule(project_id: uuid.UUID, wid: uuid.UUID, body: RescheduleIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    """Moves or resizes a task. The baseline is untouched: each changed date becomes a date revision with the reason, approved at once only for
    callers who may approve. Refuses a start before a predecessor finishes; reports successors that the move now squeezes."""
    project = project_or_404(db, user, project_id)
    w = wi_or_404(db, project_id, wid)
    cur_s, cur_f = current_range(w)
    new_s, new_f = body.start or cur_s, body.finish or cur_f
    if w.kind == "milestone":  # a milestone is a single date
        d = body.finish or body.start
        if d is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Send the new date")
        new_s = new_f = d
    if new_s is None and new_f is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Send a start or a finish date")
    if new_s and new_f and new_f < new_s:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The finish would be before the start")
    if body.approve and "plan:approve" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: plan:approve")
    names = {i.id: i for i in db.scalars(select(WorkItem).where(WorkItem.project_id == project_id))}
    preds = db.scalars(select(WorkItemDependency).where(WorkItemDependency.successor_id == wid)).all()
    succs = db.scalars(select(WorkItemDependency).where(WorkItemDependency.predecessor_id == wid)).all()
    for d in preds:  # hard rule: this task may not start before a predecessor finishes
        p = names.get(d.predecessor_id)
        pf = current_range(p)[1] if p else None
        if pf and new_s and new_s < pf + timedelta(days=d.lag_days or 0):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"It cannot start on {new_s.isoformat()}: predecessor '{p.title}' finishes {pf.isoformat()}" + (f" (+{d.lag_days} d lag)" if d.lag_days else ""))
    changes = []
    if new_s != cur_s and new_s is not None:
        changes.append(("planned_start", new_s))
    if new_f != cur_f and new_f is not None:
        changes.append(("planned_finish", new_f))
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The dates are unchanged")
    revs = [create_revision(db, user, project, "work_item", w, RevisionIn(field=f, new_date=v, reason=body.reason, approve=False)) for f, v in changes]
    if body.approve:  # later shifts approve the finish first, earlier shifts the start first, so the range is valid at every step
        later = (new_s and cur_s and new_s > cur_s) or (new_f and cur_f and new_f > cur_f)
        for r in sorted(revs, key=lambda r: (r.field != "planned_finish") if later else (r.field != "planned_start")):
            decide(db, user, "work_item", w, r, True)
    conflicts = []
    if body.approve:
        f_now = current_range(w)[1]
        for d in succs:
            sc = names.get(d.successor_id)
            ss = current_range(sc)[0] if sc else None
            if f_now and ss and ss < f_now + timedelta(days=d.lag_days or 0):
                conflicts.append({"id": str(sc.id), "title": sc.title, "starts": ss.isoformat(), "earliest": (f_now + timedelta(days=d.lag_days or 0)).isoformat()})
    db.commit()
    phases = {p.id: p.name for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id))}
    return {"item": wi_out(w, project, date.today(), phases), "applied": body.approve, "revisions": [_rev_out(r) for r in revs], "successor_conflicts": conflicts}


# ------------------------------------------------------------------ phases (add / rename / remove when empty)
class PhaseIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)


def _phase_name_free(db: Session, project_id: uuid.UUID, name: str, ignore: uuid.UUID | None = None) -> None:
    for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id)):
        if p.id != ignore and norm(p.name) == norm(name):
            raise HTTPException(status.HTTP_409_CONFLICT, f"A phase called '{p.name}' already exists")


@router.post("/{project_id}/phases", status_code=status.HTTP_201_CREATED)
def create_phase(project_id: uuid.UUID, body: PhaseIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    name = " ".join(body.name.split())
    _phase_name_free(db, project_id, name)
    last = db.scalar(select(func.max(ProjectPhase.sort_order)).where(ProjectPhase.project_id == project_id)) or 0
    ph = ProjectPhase(project_id=project_id, name=name, sort_order=last + 1)
    db.add(ph)
    db.flush()
    write_audit(db, user, "create", "project_phase", ph.id, after=row_to_dict(ph))
    db.commit()
    return {"id": ph.id, "name": ph.name}


@router.patch("/{project_id}/phases/{phase_id}")
def rename_phase(project_id: uuid.UUID, phase_id: uuid.UUID, body: PhaseIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    ph = db.get(ProjectPhase, phase_id)
    if ph is None or ph.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase not found")
    name = " ".join(body.name.split())
    _phase_name_free(db, project_id, name, ph.id)
    before = row_to_dict(ph)
    ph.name = name
    write_audit(db, user, "update", "project_phase", ph.id, before=before, after=row_to_dict(ph))
    db.commit()
    return {"id": ph.id, "name": ph.name}


@router.delete("/{project_id}/phases/{phase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phase(project_id: uuid.UUID, phase_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    ph = db.get(ProjectPhase, phase_id)
    if ph is None or ph.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phase not found")
    if db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.phase_id == phase_id).execution_options(lifecycle="all")):
        raise HTTPException(status.HTTP_409_CONFLICT, "The phase still has tasks (including archived or trashed ones). Move or purge them first")
    write_audit(db, user, "delete", "project_phase", ph.id, before=row_to_dict(ph))
    db.delete(ph)
    db.commit()
