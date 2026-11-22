"""Archive, restore, soft delete, purge, duplicate and bulk update for every managed record type (plan tasks, gates, pending items,
delivery items, requirements, helpdesk items, gap specs, discussions, scope decisions, action items).

  archive  active -> archived        hidden from lists and dashboards, kept as it was
  delete   active/archived -> trash  reversible; links and revision history stay
  restore  archived/trash -> active
  purge    trash -> gone             irreversible; needs projects:create and an explicit confirm
  duplicate                          a new record from an active one: revisions, actuals, links and import origin are NOT copied
Bulk actions are all-or-nothing for field updates (one invalid value stops everything), and report skipped rows for state changes.
"""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.api.plan import _check_refs, project_or_404
from app.api.records import BY_TYPE, Spec, _apply, _t
from app.core.audit import row_to_dict, write_audit
from app.core.deps import get_db, require
from app.core.lifecycle import move, purge, state_of
from app.db.base import utcnow
from app.models import User
from app.models.canonical import DependencyItem, WorkItem

router = APIRouter()
ACTIONS = ("archive", "restore", "delete", "purge", "duplicate")
MAX_BULK = 200

# plan-side types share the same engine; their dates move only through revisions, so dates are not bulk-editable
MANAGED: dict[str, Spec] = {
    **BY_TYPE,
    "work_item": Spec("work-items", "work_item", WorkItem, lambda o: _t(o.title), ["title"], [],
                      {"owner_name": "str", "responsible_party": "str", "product_id": "uuid", "phase_id": "uuid", "remarks": "text",
                       "delivery_mode": "choice:onsite|online", "location_label": "str"}, ["title"], ["sort_order"], "work_item"),
    "dependency_item": Spec("pending-items", "dependency_item", DependencyItem, lambda o: _t(o.description), ["description"], [],
                            {"owner_name": "str", "remarks": "text", "category": "str", "product_id": "uuid"}, ["description"], ["sort_order"], "dependency"),
}
# reset when duplicating: a copy is a new, not-yet-started record
RESET = {"action_item": {"status": "open", "escalation_level": 0, "escalated_to": None, "escalated_at": None, "escalation_reason": None,
                         "resolved_at": None, "resolved_by_email": None, "resolution_note": None, "reopen_count": 0,
                         "last_action": "Duplicated", "last_action_by": None, "last_action_at": None},
         "delivery_item": {"sources": ["manual"], "merge_notes": None},
         "approval_gate": {"approval_status": None, "approval_category": None, "submission_date": None, "signoff_date": None},
         "coverage_activity": {"completed_count": 0},
         "week_plan_item": {"status": "planned", "percent_complete": None},
         "uat_scenario": {"result": "not_run", "result_raw": None, "executed_date": None, "defect_ref": None},
         "uat_defect": {"status": "open", "closed_on": None, "resolution": None},
         "integration_item": {"status_raw": None, "status_category": None, "uat_status": None},
         "report_item": {"status_raw": None, "status_category": None, "uat_status": None}}
SKIP = {"id", "created_at", "updated_at", "archived_at", "archived_by", "deleted_at", "deleted_by", "import_batch_id", "match_key", "raw_values"}


def spec_for(type_name: str) -> Spec:
    s = MANAGED.get(type_name)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown record type")
    return s


def load(db: Session, spec: Spec, pid: uuid.UUID, rid: uuid.UUID) -> Any:
    o = db.get(spec.model, rid, execution_options={"lifecycle": "all"})
    if o is None or o.project_id != pid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    return o


def _check_transition(action: str, o: Any) -> str | None:
    """None if allowed, else the reason it is not."""
    st = state_of(o)
    ok = {"archive": st == "active", "delete": st in ("active", "archived"), "restore": st in ("archived", "deleted"),
          "purge": st == "deleted", "duplicate": st == "active"}[action]
    if ok:
        return None
    return {"purge": "Only records in the trash can be permanently deleted", "duplicate": "Only active records can be duplicated"}.get(action, f"Cannot {action} a record that is {st}")


def _need_permissions(user: User, action: str) -> None:
    if action == "purge" and "projects:create" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: projects:create (permanent deletion)")


def _duplicate(db: Session, user: User, spec: Spec, o: Any) -> Any:
    vals: dict[str, Any] = {}
    for c in inspect(o).mapper.column_attrs:
        k = c.key
        if k in SKIP:
            continue
        vals[k] = None if (k.startswith("revised_") or k.startswith("actual_")) else getattr(o, k)
    vals.update(RESET.get(spec.type_name, {}))
    if hasattr(spec.model, "match_key"):
        vals["match_key"] = ""
    last = db.scalar(select(func.max(spec.model.sort_order)).where(spec.model.project_id == o.project_id)) or 0
    vals["sort_order"] = last + 1
    title_field = spec.required_on_create[0]
    vals[title_field] = f"{getattr(o, title_field) or ''} (copy)"[: getattr(spec.model, title_field).property.columns[0].type.length or 10_000]
    if spec.type_name == "action_item":
        vals["last_action_by"], vals["last_action_at"] = user.email, utcnow()
    copy = spec.model(**vals)
    db.add(copy)
    db.flush()
    write_audit(db, user, "duplicate", spec.type_name, copy.id, after={"copied_from": str(o.id), **row_to_dict(copy)})
    return copy


class ActionIn(BaseModel):
    confirm: bool = False


def _do(db: Session, user: User, spec: Spec, o: Any, action: str) -> Any:
    if action == "purge":
        purge(db, user, spec.type_name, o)
        return None
    if action == "duplicate":
        return _duplicate(db, user, spec, o)
    move(db, user, spec.type_name, o, action)
    return o


# ------------------------------------------------------------------ views of what is archived / in the trash
@router.get("/{project_id}/lifecycle")
def summary(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    """How many records are archived / in the trash, per type (for the badges on the Archive & trash view)."""
    project_or_404(db, user, project_id)
    out = {}
    for t, spec in MANAGED.items():
        for st in ("archived", "deleted"):
            n = db.scalar(select(func.count()).select_from(spec.model).where(spec.model.project_id == project_id).execution_options(lifecycle=st)) or 0
            if n:
                out.setdefault(t, {})[st] = n
    return out


@router.get("/{project_id}/lifecycle/{type_name}")
def list_inactive(project_id: uuid.UUID, type_name: str, state: str = Query("archived", pattern="^(archived|deleted)$"),
                  page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                  db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    spec = spec_for(type_name)
    project_or_404(db, user, project_id)
    stmt = select(spec.model).where(spec.model.project_id == project_id).execution_options(lifecycle=state)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()).execution_options(lifecycle=state)) or 0
    col = spec.model.deleted_at if state == "deleted" else spec.model.archived_at
    rows = db.scalars(stmt.order_by(col.desc(), spec.model.id).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "page": page, "size": size, "items": [
        {"id": r.id, "type": type_name, "title": spec.title(r), "state": state_of(r), "archived_at": r.archived_at, "deleted_at": r.deleted_at} for r in rows]}


# ------------------------------------------------------------------ one record
@router.post("/{project_id}/lifecycle/{type_name}/{rid}/{action}")
def act(project_id: uuid.UUID, type_name: str, rid: uuid.UUID, action: str, body: ActionIn | None = None,
        db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    if action not in ACTIONS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown action")
    spec = spec_for(type_name)
    project_or_404(db, user, project_id)
    _need_permissions(user, action)
    o = load(db, spec, project_id, rid)
    if action == "purge" and not (body and body.confirm):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Permanent deletion cannot be undone: send confirm=true")
    why = _check_transition(action, o)
    if why:
        raise HTTPException(status.HTTP_409_CONFLICT, why)
    result = _do(db, user, spec, o, action)
    db.commit()
    return {"id": result.id if result is not None else None, "state": state_of(result) if result is not None else "purged", "title": spec.title(result) if result is not None else None}


# ------------------------------------------------------------------ many records
class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK)
    action: str = Field(pattern="^(archive|restore|delete|purge|duplicate|update)$")
    fields: dict[str, Any] = {}
    confirm: bool = False


@router.post("/{project_id}/lifecycle/{type_name}/bulk")
def bulk(project_id: uuid.UUID, type_name: str, body: BulkIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    spec = spec_for(type_name)
    project = project_or_404(db, user, project_id)
    if body.action in ("delete", "purge") and not body.confirm:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Bulk {body.action} needs confirm=true")
    if body.action == "update" and not body.fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to update: send fields")
    _need_permissions(user, body.action)
    ids = list(dict.fromkeys(body.ids))
    objs = []
    for rid in ids:  # unknown id or another project's record stops everything, so the caller never gets a half-applied answer
        objs.append(load(db, spec, project_id, rid))
    done, skipped, label = 0, [], ""
    try:
        for o in objs:
            label = spec.title(o)
            if body.action == "update":
                if state_of(o) != "active":
                    skipped.append({"id": str(o.id), "reason": f"record is {state_of(o)}"})
                    continue
                before = row_to_dict(o)
                _apply(db, spec, o, dict(body.fields), user)
                if spec.type_name == "work_item":
                    _check_refs(db, project, {k: (uuid.UUID(str(v)) if v else None) for k, v in body.fields.items() if k in ("phase_id", "product_id")})
                write_audit(db, user, "update", spec.type_name, o.id, before=before, after=row_to_dict(o))
            else:
                why = _check_transition(body.action, o)
                if why:
                    skipped.append({"id": str(o.id), "reason": why})
                    continue
                _do(db, user, spec, o, body.action)
            done += 1
    except HTTPException as e:
        db.rollback()
        raise HTTPException(e.status_code, f"{e.detail} (record {label}); nothing was changed") from None
    db.commit()
    return {"done": done, "skipped": skipped}
