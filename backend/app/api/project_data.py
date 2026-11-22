"""Read access to imported/canonical project records (full planning UI arrives in Phase 3)."""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session

from app.core.deps import ensure_project_access, get_db, require
from app.models import ProjectPhase, User
from app.models.canonical import ApprovalGate, GapSpecification, TrackerEvent

router = APIRouter()
_HIDE = {"raw_values", "match_key"}


def _row(obj: Any) -> dict:
    return jsonable_encoder({c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key not in _HIDE})


def _page(db: Session, user: User, project_id: uuid.UUID, model: Any, page: int, size: int, filters: list, order: list):
    ensure_project_access(db, user, project_id)
    stmt = select(model).where(model.project_id == project_id, *filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(*order).offset((page - 1) * size).limit(size)).all()
    return {"items": [_row(r) for r in rows], "total": total, "page": page, "size": size}


@router.get("/{project_id}/phases")
def phases(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    ensure_project_access(db, user, project_id)
    return [_row(p) for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id).order_by(ProjectPhase.sort_order))]


@router.get("/{project_id}/tracker-events")
def tracker_events(project_id: uuid.UUID, product_id: uuid.UUID | None = None, page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=200),
                   db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    f = [TrackerEvent.product_id == product_id] if product_id else []
    return _page(db, user, project_id, TrackerEvent, page, size, f, [TrackerEvent.product_id, TrackerEvent.sort_order])


@router.get("/{project_id}/approval-gates")
def approval_gates(project_id: uuid.UUID, gate_type: str | None = None, page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=200),
                   db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    f = [ApprovalGate.gate_type == gate_type] if gate_type else []
    return _page(db, user, project_id, ApprovalGate, page, size, f, [ApprovalGate.gate_type, ApprovalGate.sort_order])


@router.get("/{project_id}/gap-specifications")
def gap_specs(project_id: uuid.UUID, q: str | None = None, issue_id: str | None = None, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
              db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    f = []
    if q:
        f.append(or_(GapSpecification.description.ilike(f"%{q}%"), GapSpecification.module.ilike(f"%{q}%")))
    if issue_id:
        f.append(GapSpecification.external_issue_id == issue_id)
    return _page(db, user, project_id, GapSpecification, page, size, f, [GapSpecification.sort_order])
