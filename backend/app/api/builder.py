"""Dashboard builder: widget types, saved layouts (personal / project / management), the user's chosen layout per project, and widget data.

Who may do what:
  personal    only the owner sees and edits it
  project     everyone with access to the project sees it; editing needs projects:write on that project
  management  everyone sees it; creating, editing and deleting needs dashboards:manage
Every layout save names the version it started from; a stale save is refused (409) so two editors never overwrite each other.
"""
import copy
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.plan import project_or_404
from app.core.audit import row_to_dict, write_audit
from app.core.deps import accessible_project_ids, get_db, require
from app.models import Project, User
from app.models.workspace import DashboardLayout, DashboardPref
from app.modules.dashboards import widgets

router = APIRouter()
TEMPLATE_PREFIX = "template:"


def _template(key: str) -> dict:
    t = widgets.TEMPLATES.get(key)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown template")
    return t


def can_see(db: Session, user: User, l: DashboardLayout) -> bool:
    if l.scope == "personal":
        return l.owner_id == user.id
    if l.scope == "management":
        return True
    allowed = accessible_project_ids(db, user)
    return allowed is None or l.project_id in allowed


def can_edit(db: Session, user: User, l: DashboardLayout) -> bool:
    if not can_see(db, user, l):
        return False
    if l.scope == "personal":
        return True
    return ("dashboards:manage" if l.scope == "management" else "projects:write") in user.permission_codes


def _summary(db: Session, user: User, l: DashboardLayout) -> dict:
    return {"id": str(l.id), "scope": l.scope, "name": l.name, "project_id": str(l.project_id) if l.project_id else None, "version": l.version, "widgets": len(l.config.get("widgets", [])),
            "updated_at": l.updated_at, "updated_by": l.updated_by_email, "can_edit": can_edit(db, user, l)}


def _template_summary(key: str) -> dict:
    t = _template(key)
    return {"id": TEMPLATE_PREFIX + key, "scope": "template", "name": t["name"], "description": t["description"], "project_id": None, "version": 0,
            "widgets": len(t["config"]["widgets"]), "updated_at": None, "updated_by": None, "can_edit": False}


def _get(db: Session, user: User, layout_id: str) -> DashboardLayout:
    try:
        l = db.get(DashboardLayout, uuid.UUID(layout_id))
    except ValueError:
        l = None
    if l is None or not can_see(db, user, l):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found")  # 404, not 403: a layout you cannot see does not exist for you
    return l


def _name_free(db: Session, scope: str, owner: uuid.UUID | None, project: uuid.UUID | None, name: str, ignore: uuid.UUID | None = None) -> None:
    stmt = select(DashboardLayout).where(DashboardLayout.scope == scope, func.lower(DashboardLayout.name) == name.lower())
    if scope == "personal":
        stmt = stmt.where(DashboardLayout.owner_id == owner)
    elif scope == "project":
        stmt = stmt.where(DashboardLayout.project_id == project)
    for l in db.scalars(stmt):
        if l.id != ignore:
            raise HTTPException(status.HTTP_409_CONFLICT, f"You already have a {scope} dashboard called '{l.name}'")


# ------------------------------------------------------------------ widget types and data
@router.get("/widget-types")
def widget_types(user: User = Depends(require("projects:read"))):
    """The palette: every widget type with its settings, so the editor builds its forms from this and never needs changing for a new type."""
    return {"grid_columns": widgets.GRID_COLS, "types": [widgets.describe(w) for w in widgets.REGISTRY.values()]}


class WidgetDataIn(BaseModel):
    config: dict = {}
    filters: dict = {}
    as_of: date | None = None


@router.post("/projects/{project_id}/widgets/{wtype}/data")
def widget_data(project_id: uuid.UUID, wtype: str, body: WidgetDataIn, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project = project_or_404(db, user, project_id)
    return jsonable_encoder(widgets.widget_data(db, project, wtype, body.config, body.filters, body.as_of or date.today()))


# ------------------------------------------------------------------ layouts
@router.get("/dashboard-layouts")
def list_layouts(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project_or_404(db, user, project_id)
    rows = db.scalars(select(DashboardLayout).where(or_(
        (DashboardLayout.scope == "management"),
        (DashboardLayout.scope == "project") & (DashboardLayout.project_id == project_id),
        (DashboardLayout.scope == "personal") & (DashboardLayout.owner_id == user.id))).order_by(DashboardLayout.name)).all()
    pref = db.get(DashboardPref, (user.id, project_id))
    ids = {TEMPLATE_PREFIX + k for k in widgets.TEMPLATES} | {str(r.id) for r in rows}
    active = pref.layout_id if pref and pref.layout_id in ids else TEMPLATE_PREFIX + "status"
    return jsonable_encoder({"items": [_template_summary(k) for k in widgets.TEMPLATES] + [_summary(db, user, r) for r in rows], "active_id": active})


@router.get("/dashboard-layouts/{layout_id}")
def get_layout(layout_id: str, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    if layout_id.startswith(TEMPLATE_PREFIX):
        return {**_template_summary(layout_id[len(TEMPLATE_PREFIX):]), "config": copy.deepcopy(_template(layout_id[len(TEMPLATE_PREFIX):])["config"])}
    l = _get(db, user, layout_id)
    return jsonable_encoder({**_summary(db, user, l), "config": l.config})


class LayoutCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(pattern="^(personal|project|management)$")
    project_id: uuid.UUID | None = None
    config: dict | None = None
    from_id: str | None = None  # duplicate: copy the settings of this layout (or template)


def _source_config(db: Session, user: User, from_id: str) -> dict:
    if from_id.startswith(TEMPLATE_PREFIX):
        return copy.deepcopy(_template(from_id[len(TEMPLATE_PREFIX):])["config"])
    return copy.deepcopy(_get(db, user, from_id).config)


@router.post("/dashboard-layouts", status_code=status.HTTP_201_CREATED)
def create_layout(body: LayoutCreate, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    name = " ".join(body.name.split())
    if body.scope == "project":
        if body.project_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A project dashboard needs a project")
        project_or_404(db, user, body.project_id)
        if "projects:write" not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: projects:write (project dashboards)")
    elif body.scope == "management":
        if "dashboards:manage" not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: dashboards:manage (organisation-wide dashboards)")
    elif body.project_id is not None:
        project_or_404(db, user, body.project_id)
    owner = user.id if body.scope == "personal" else None
    project = body.project_id if body.scope == "project" else None
    _name_free(db, body.scope, owner, project, name)
    cfg = body.config if body.config is not None else _source_config(db, user, body.from_id) if body.from_id else {"version": 1, "filters": {}, "widgets": []}
    l = DashboardLayout(name=name, scope=body.scope, owner_id=owner, project_id=project, config=widgets.validate_layout(db, cfg), version=1,
                        created_by_email=user.email, updated_by_email=user.email)
    db.add(l)
    db.flush()
    write_audit(db, user, "create", "dashboard_layout", l.id, after={"name": l.name, "scope": l.scope, "widgets": len(l.config["widgets"]), "from": body.from_id})
    db.commit()
    return jsonable_encoder({**_summary(db, user, l), "config": l.config})


class LayoutSave(BaseModel):
    version: int
    name: str | None = Field(None, min_length=1, max_length=120)
    config: dict | None = None


def _editable(db: Session, user: User, layout_id: str) -> DashboardLayout:
    if layout_id.startswith(TEMPLATE_PREFIX):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The default template cannot be changed. Duplicate it to make your own")
    l = _get(db, user, layout_id)
    if not can_edit(db, user, l):
        need = {"project": "projects:write", "management": "dashboards:manage"}.get(l.scope, "ownership")
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"You cannot change this {l.scope} dashboard (needs {need})")
    return l


@router.put("/dashboard-layouts/{layout_id}")
def save_layout(layout_id: str, body: LayoutSave, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    l = _editable(db, user, layout_id)
    if body.version != l.version:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Someone saved this dashboard after you opened it (now version {l.version}). Reload it, then apply your changes again")
    before = {"name": l.name, "widgets": len(l.config["widgets"]), "version": l.version}
    if body.name:
        name = " ".join(body.name.split())
        _name_free(db, l.scope, l.owner_id, l.project_id, name, l.id)
        l.name = name
    if body.config is not None:
        l.config = widgets.validate_layout(db, body.config)
    l.version += 1
    l.updated_by_email = user.email
    write_audit(db, user, "update", "dashboard_layout", l.id, before=before, after={"name": l.name, "widgets": len(l.config["widgets"]), "version": l.version})
    db.commit()
    return jsonable_encoder({**_summary(db, user, l), "config": l.config})


class Version(BaseModel):
    version: int


@router.post("/dashboard-layouts/{layout_id}/restore-default")
def restore_default(layout_id: str, body: Version, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    """Puts the default template's arrangement back into this layout."""
    l = _editable(db, user, layout_id)
    if body.version != l.version:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Someone saved this dashboard after you opened it (now version {l.version}). Reload it first")
    before = {"widgets": len(l.config["widgets"]), "version": l.version}
    l.config = widgets.validate_layout(db, copy.deepcopy(_template("status")["config"]))
    l.version += 1
    l.updated_by_email = user.email
    write_audit(db, user, "restore_default", "dashboard_layout", l.id, before=before, after={"widgets": len(l.config["widgets"]), "version": l.version})
    db.commit()
    return jsonable_encoder({**_summary(db, user, l), "config": l.config})


@router.delete("/dashboard-layouts/{layout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_layout(layout_id: str, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    l = _editable(db, user, layout_id)
    write_audit(db, user, "delete", "dashboard_layout", l.id, before=row_to_dict(l))
    db.query(DashboardPref).filter(DashboardPref.layout_id == str(l.id)).delete(synchronize_session=False)
    db.delete(l)
    db.commit()


# ------------------------------------------------------------------ the layout a user last chose, per project
class PrefIn(BaseModel):
    layout_id: str | None = None


@router.put("/projects/{project_id}/dashboard-pref")
def set_pref(project_id: uuid.UUID, body: PrefIn, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project_or_404(db, user, project_id)
    lid = body.layout_id or TEMPLATE_PREFIX + "status"
    if lid.startswith(TEMPLATE_PREFIX):
        _template(lid[len(TEMPLATE_PREFIX):])
    else:
        l = _get(db, user, lid)
        if l.scope == "project" and l.project_id != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found")
    pref = db.get(DashboardPref, (user.id, project_id))
    if pref is None:
        db.add(DashboardPref(user_id=user.id, project_id=project_id, layout_id=lid))
    else:
        pref.layout_id = lid
    db.commit()
    return {"layout_id": lid}
