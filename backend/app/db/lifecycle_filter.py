"""One place decides which rows every query sees.

Default ("active"): not archived and not deleted, for every model that has LifecycleMixin. So lists, facets, counts, the plan and every
dashboard ignore archived and trashed records without each query remembering to. Override per statement with
.execution_options(lifecycle="archived" | "deleted" | "all") or per session with session.info["lifecycle"] (imports use "all").
"""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.canonical import LifecycleMixin


# One function per mode (not a closure over the mode): SQLAlchemy caches compiled statements by the function's code, so a shared
# closure would let the first mode's filter leak into every later query.
def _active(cls):
    return (cls.archived_at.is_(None)) & (cls.deleted_at.is_(None))


def _archived(cls):
    return (cls.archived_at.is_not(None)) & (cls.deleted_at.is_(None))


def _deleted(cls):
    return cls.deleted_at.is_not(None)


_BY_MODE = {"active": _active, "archived": _archived, "deleted": _deleted}


@event.listens_for(Session, "do_orm_execute")
def _lifecycle_filter(state) -> None:
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    mode = state.execution_options.get("lifecycle") or state.session.info.get("lifecycle", "active")
    if mode == "all":
        return
    state.statement = state.statement.options(with_loader_criteria(LifecycleMixin, _BY_MODE.get(mode, _active), include_aliases=True))
