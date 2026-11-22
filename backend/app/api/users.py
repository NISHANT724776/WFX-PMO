import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import row_to_dict, write_audit
from app.core.deps import get_db, require
from app.core.security import MIN_PASSWORD_LENGTH, hash_password
from app.models import Project, Role, User, UserProjectAccess
from app.schemas.common import ORMModel, Page

router = APIRouter()


class RoleOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    is_global_scope: bool


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    role: RoleOut


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    role_code: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=150)
    is_active: Optional[bool] = None
    role_code: Optional[str] = None
    password: Optional[str] = Field(None, min_length=MIN_PASSWORD_LENGTH, max_length=200)


class ProjectAccessIn(BaseModel):
    project_ids: list[uuid.UUID]


def _role(db: Session, code: str) -> Role:
    role = db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown role: {code}")
    return role


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _: User = Depends(require("users:read"))):
    return db.scalars(select(Role).order_by(Role.name)).all()


@router.get("", response_model=Page[UserOut])
def list_users(
    q: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require("users:read")),
):
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(User.email).offset((page - 1) * size).limit(size)).all()
    return {"items": rows, "total": total, "page": page, "size": size}


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db), actor: User = Depends(require("users:write"))):
    role = _role(db, body.role_code)
    user = User(
        email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password), role_id=role.id
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from e
    write_audit(db, actor, "create", "user", user.id, after=row_to_dict(user))
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, body: UserUpdate, db: Session = Depends(get_db), actor: User = Depends(require("users:write"))
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id and (body.is_active is False or (body.role_code and body.role_code != actor.role.code)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate or change the role of your own account")
    before = row_to_dict(user)
    data = body.model_dump(exclude_unset=True)
    if "role_code" in data:
        user.role_id = _role(db, data.pop("role_code")).id
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    for k, v in data.items():
        setattr(user, k, v)
    write_audit(db, actor, "update", "user", user.id, before=before, after=row_to_dict(user))
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}/project-access", response_model=list[uuid.UUID])
def get_project_access(user_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require("users:read"))):
    rows = db.scalars(select(UserProjectAccess.project_id).where(UserProjectAccess.user_id == user_id)).all()
    return list(rows)


@router.put("/{user_id}/project-access", response_model=list[uuid.UUID])
def set_project_access(
    user_id: uuid.UUID, body: ProjectAccessIn, db: Session = Depends(get_db), actor: User = Depends(require("users:write"))
):
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    ids = set(body.project_ids)
    found = set(db.scalars(select(Project.id).where(Project.id.in_(ids))).all()) if ids else set()
    if found != ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "One or more project ids do not exist")
    old = set(db.scalars(select(UserProjectAccess.project_id).where(UserProjectAccess.user_id == user_id)).all())
    db.query(UserProjectAccess).filter(UserProjectAccess.user_id == user_id).delete()
    for pid in ids:
        db.add(UserProjectAccess(user_id=user_id, project_id=pid))
    write_audit(
        db, actor, "update", "user_project_access", user_id,
        before={"project_ids": sorted(map(str, old))}, after={"project_ids": sorted(map(str, ids))},
    )
    db.commit()
    return sorted(ids)
