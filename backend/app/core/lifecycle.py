"""Archive / soft delete / restore / purge for any record with LifecycleMixin. Pure data operations; the API decides who may call them."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import row_to_dict, write_audit
from app.db.base import utcnow
from app.models import User
from app.models.canonical import RequirementLink, DateRevision, WorkItem

TRASH_FIRST = ("delete",)


def state_of(o: Any) -> str:
    return "deleted" if o.deleted_at else "archived" if o.archived_at else "active"


def _children(db: Session, o: Any) -> list[Any]:
    """Sub-tasks travel with their parent, in whatever state they are."""
    if isinstance(o, WorkItem):
        return list(db.scalars(select(WorkItem).where(WorkItem.parent_id == o.id).execution_options(lifecycle="all")))
    return []


def _stamp(db: Session, user: User, o: Any, kind: str, now: datetime) -> None:
    if kind == "archive":
        o.archived_at, o.archived_by = now, user.id
    else:
        o.deleted_at, o.deleted_by = now, user.id


def move(db: Session, user: User, type_name: str, o: Any, action: str) -> None:
    """action: archive | delete | restore. Records the change in the audit log with the state before and after."""
    now = utcnow()
    before = {"state": state_of(o)}
    touched = [o] + _children(db, o)
    if action in ("archive", "delete"):
        for x in touched:
            if action == "delete" and not x.deleted_at:
                _stamp(db, user, x, "delete", now)
            elif action == "archive" and not x.archived_at and not x.deleted_at:
                _stamp(db, user, x, "archive", now)
    elif action == "restore":
        was_deleted = o.deleted_at is not None
        stamp = o.deleted_at if was_deleted else o.archived_at  # sub-tasks that went with the parent carry the same stamp
        for x in touched:
            if was_deleted and (x is o or x.deleted_at == stamp):
                x.deleted_at = x.deleted_by = None
            elif not was_deleted and (x is o or x.archived_at == stamp):
                x.archived_at = x.archived_by = None
    else:
        raise ValueError(action)
    write_audit(db, user, action, type_name, o.id, before=before, after={"state": state_of(o), "with_children": len(touched) - 1})


def purge(db: Session, user: User, type_name: str, o: Any) -> None:
    """Permanent removal. Only records already in the trash get here (the API checks)."""
    for x in _children(db, o):
        db.delete(x)
    db.query(RequirementLink).filter((RequirementLink.source_id == o.id) | (RequirementLink.target_id == o.id)).delete(synchronize_session=False)
    db.query(DateRevision).filter(DateRevision.entity_id == o.id).delete(synchronize_session=False)
    write_audit(db, user, "purge", type_name, o.id, before=row_to_dict(o))
    db.delete(o)
