import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import row_to_dict, write_audit
from app.core.deps import accessible_project_ids, ensure_project_access, get_db, require
from app.models import Customer, Project, ProjectProduct, ProjectSite, User
from app.schemas.common import Page
from app.schemas.master import AddProduct, AddSite, ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter()


def _commit(db: Session, what: str):
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"{what}: duplicate value or invalid reference") from e


def _load(db: Session, user: User, project_id: uuid.UUID) -> Project:
    ensure_project_access(db, user, project_id)
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


@router.get("", response_model=Page[ProjectRead])
def list_projects(
    q: str | None = None,
    customer_id: uuid.UUID | None = None,
    status_: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("projects:read")),
):
    stmt = select(Project)
    allowed = accessible_project_ids(db, user)
    if allowed is not None:  # record-level scoping enforced in the query itself
        stmt = stmt.where(Project.id.in_(allowed or {uuid.UUID(int=0)}))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Project.name.ilike(like), Project.code.ilike(like)))
    if customer_id:
        stmt = stmt.where(Project.customer_id == customer_id)
    if status_:
        stmt = stmt.where(Project.status == status_)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Project.created_at, Project.id).offset((page - 1) * size).limit(size)).all()
    return {"items": rows, "total": total, "page": page, "size": size}


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    return _load(db, user, project_id)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(require("projects:create"))):
    if db.get(Customer, body.customer_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown customer_id")
    if body.start_date and body.target_go_live and body.target_go_live < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "target_go_live is before start_date")
    p = Project(**body.model_dump())
    db.add(p)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Project code already exists") from e
    write_audit(db, user, "create", "project", p.id, after=row_to_dict(p))
    _commit(db, "project")
    return p


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("projects:write")),
):
    p = _load(db, user, project_id)
    before = row_to_dict(p)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    if p.start_date and p.target_go_live and p.target_go_live < p.start_date:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "target_go_live is before start_date")
    write_audit(db, user, "update", "project", p.id, before=before, after=row_to_dict(p))
    _commit(db, "project")
    return p


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:create"))):
    p = _load(db, user, project_id)
    write_audit(db, user, "delete", "project", p.id, before=row_to_dict(p))
    db.delete(p)
    _commit(db, "project")


@router.post("/{project_id}/products", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def add_product(
    project_id: uuid.UUID, body: AddProduct, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))
):
    p = _load(db, user, project_id)
    link = ProjectProduct(project_id=p.id, **body.model_dump())
    db.add(link)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Product already on project or unknown product") from e
    write_audit(db, user, "create", "project_product", link.id, after=row_to_dict(link))
    _commit(db, "project product")
    db.refresh(p)
    return p


@router.delete("/{project_id}/products/{link_id}", response_model=ProjectRead)
def remove_product(
    project_id: uuid.UUID, link_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))
):
    p = _load(db, user, project_id)
    link = db.get(ProjectProduct, link_id)
    if link is None or link.project_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project product not found")
    write_audit(db, user, "delete", "project_product", link.id, before=row_to_dict(link))
    db.delete(link)
    _commit(db, "project product")
    db.refresh(p)
    return p


@router.post("/{project_id}/sites", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def add_site(
    project_id: uuid.UUID, body: AddSite, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))
):
    p = _load(db, user, project_id)
    site = ProjectSite(project_id=p.id, **body.model_dump())
    db.add(site)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Site already on project or unknown location") from e
    write_audit(db, user, "create", "project_site", site.id, after=row_to_dict(site))
    _commit(db, "project site")
    db.refresh(p)
    return p


@router.delete("/{project_id}/sites/{site_id}", response_model=ProjectRead)
def remove_site(
    project_id: uuid.UUID, site_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))
):
    p = _load(db, user, project_id)
    site = db.get(ProjectSite, site_id)
    if site is None or site.project_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project site not found")
    write_audit(db, user, "delete", "project_site", site.id, before=row_to_dict(site))
    db.delete(site)
    _commit(db, "project site")
    db.refresh(p)
    return p
