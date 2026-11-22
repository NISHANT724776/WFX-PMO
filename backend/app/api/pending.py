"""Pending activities register: pending with Customer / WFX / External partner / Internal team."""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.api.plan import (
    HIDE, RevisionIn, _apply_status_generic, create_revision, project_or_404, revisions_out,
)
from app.core.lifecycle import move
from app.core.audit import row_to_dict, write_audit
from app.core.deps import get_db, require
from app.models import Product, Project, User
from app.models.canonical import DateRevision, DependencyItem, WorkItem
from app.modules.planning.delays import assess

router = APIRouter()
PENDING_WITH = "^(customer|wfx|external|internal)$"


def di_or_404(db: Session, pid: uuid.UUID, did: uuid.UUID) -> DependencyItem:
    d = db.get(DependencyItem, did)
    if d is None or d.project_id != pid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pending item not found")
    return d


def di_out(d: DependencyItem, project: Project, as_of: date) -> dict:
    out = {c.key: getattr(d, c.key) for c in inspect(d).mapper.column_attrs if c.key not in HIDE}
    a = assess(None, d.original_target_date, None, d.revised_target_date, d.status_category, None, d.actual_closure_date, as_of, project.delay_grace_days or 0)
    out.update(effective_target_date=a.effective_finish, is_overdue=a.overdue, days_late=a.days_late, slippage_days=a.slippage_days, is_closed=a.closed)
    return jsonable_encoder(out)


@router.get("/{project_id}/pending-items")
def list_pending(
    project_id: uuid.UUID, pending_with: str | None = Query(None, pattern=PENDING_WITH), overdue: bool | None = None,
    open_only: bool = False, product_id: uuid.UUID | None = None, q: str | None = None, as_of: date | None = None,
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(require("projects:read")),
):
    project = project_or_404(db, user, project_id)
    as_of = as_of or date.today()
    stmt = select(DependencyItem).where(DependencyItem.project_id == project_id)
    if pending_with:
        stmt = stmt.where(DependencyItem.pending_with == pending_with)
    if product_id:
        stmt = stmt.where(DependencyItem.product_id == product_id)
    if q:
        stmt = stmt.where(DependencyItem.description.ilike(f"%{q}%"))
    items = [di_out(d, project, as_of) for d in db.scalars(stmt.order_by(DependencyItem.sort_order, DependencyItem.id))]
    if overdue is not None:
        items = [i for i in items if i["is_overdue"] == overdue]
    if open_only:
        items = [i for i in items if not i["is_closed"]]
    total = len(items)
    return {"items": items[(page - 1) * size : page * size], "total": total, "page": page, "size": size, "as_of": as_of.isoformat()}


@router.get("/{project_id}/pending-summary")
def pending_summary(project_id: uuid.UUID, as_of: date | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project = project_or_404(db, user, project_id)
    as_of = as_of or date.today()
    out: dict = {k: {"open": 0, "overdue": 0, "closed": 0} for k in ("customer", "wfx", "external", "internal")}
    for d in db.scalars(select(DependencyItem).where(DependencyItem.project_id == project_id)):
        i = di_out(d, project, as_of)
        b = out[d.pending_with]
        if i["is_closed"]:
            b["closed"] += 1
        else:
            b["open"] += 1
            b["overdue"] += 1 if i["is_overdue"] else 0
    return {"as_of": as_of.isoformat(), "by_owner": out}


@router.get("/{project_id}/pending-items/{did}")
def get_pending(project_id: uuid.UUID, did: uuid.UUID, as_of: date | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project = project_or_404(db, user, project_id)
    d = di_or_404(db, project_id, did)
    out = di_out(d, project, as_of or date.today())
    out["revisions"] = revisions_out(db, "dependency_item", did)
    return out


class PendingCreate(BaseModel):
    pending_with: str = Field(pattern=PENDING_WITH)
    description: str = Field(min_length=1, max_length=2000)
    owner_name: Optional[str] = Field(None, max_length=200)
    category: Optional[str] = Field(None, max_length=200)
    product_id: Optional[uuid.UUID] = None
    original_target_date: Optional[date] = None
    remarks: Optional[str] = None
    linked_work_item_id: Optional[uuid.UUID] = None
    status: str = "not_started"


class PendingPatch(BaseModel):
    """original_target_date is the baseline and is only changed through a date revision."""

    pending_with: Optional[str] = Field(None, pattern=PENDING_WITH)
    description: Optional[str] = Field(None, min_length=1, max_length=2000)
    owner_name: Optional[str] = Field(None, max_length=200)
    category: Optional[str] = Field(None, max_length=200)
    product_id: Optional[uuid.UUID] = None
    actual_closure_date: Optional[date] = None
    remarks: Optional[str] = None
    linked_work_item_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    model_config = {"extra": "forbid"}


def _check(db: Session, project: Project, data: dict) -> None:
    if data.get("product_id") and db.get(Product, data["product_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown product")
    if data.get("linked_work_item_id"):
        w = db.get(WorkItem, data["linked_work_item_id"])
        if w is None or w.project_id != project.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linked task does not belong to this project")


@router.post("/{project_id}/pending-items", status_code=status.HTTP_201_CREATED)
def create_pending(project_id: uuid.UUID, body: PendingCreate, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project = project_or_404(db, user, project_id)
    data = body.model_dump()
    _check(db, project, data)
    code = data.pop("status")
    last = max((d.sort_order for d in db.scalars(select(DependencyItem).where(DependencyItem.project_id == project_id))), default=0)
    d = DependencyItem(project_id=project_id, match_key="", sort_order=last + 1, **data)
    _apply_status_generic(db, d, "dependency", code)
    db.add(d)
    db.flush()
    write_audit(db, user, "create", "dependency_item", d.id, after=row_to_dict(d))
    db.commit()
    return di_out(d, project, date.today())


@router.patch("/{project_id}/pending-items/{did}")
def patch_pending(project_id: uuid.UUID, did: uuid.UUID, body: PendingPatch, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project = project_or_404(db, user, project_id)
    d = di_or_404(db, project_id, did)
    data = body.model_dump(exclude_unset=True)
    _check(db, project, data)
    before = row_to_dict(d)
    code = data.pop("status", None)
    for k, v in data.items():
        setattr(d, k, v)
    if code:
        _apply_status_generic(db, d, "dependency", code)
    write_audit(db, user, "update", "dependency_item", d.id, before=before, after=row_to_dict(d))
    db.commit()
    return di_out(d, project, date.today())


@router.delete("/{project_id}/pending-items/{did}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pending(project_id: uuid.UUID, did: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    d = di_or_404(db, project_id, did)
    move(db, user, "dependency_item", d, "delete")
    db.commit()


@router.post("/{project_id}/pending-items/{did}/revisions", status_code=status.HTTP_201_CREATED)
def add_pending_revision(project_id: uuid.UUID, did: uuid.UUID, body: RevisionIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project = project_or_404(db, user, project_id)
    d = di_or_404(db, project_id, did)
    body.field = "target_date"
    create_revision(db, user, project, "dependency_item", d, body)
    db.commit()
    return revisions_out(db, "dependency_item", did)
