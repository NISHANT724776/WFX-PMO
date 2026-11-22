import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import row_to_dict, write_audit
from app.core.deps import get_db, require
from app.models import User
from app.schemas.common import Page, make_read_schema, make_update_schema


def build_crud(
    model: Any,
    create_schema: type,
    *,
    entity: str,
    search_fields: list[str],
    read_perm: str,
    write_perm: str,
) -> APIRouter:
    """Standard paginated, searchable, audited CRUD for simple master-data entities."""
    update_schema = make_update_schema(create_schema)
    read_schema = make_read_schema(create_schema)
    router = APIRouter()

    def _get(db: Session, obj_id: uuid.UUID):
        obj = db.get(model, obj_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{entity} not found")
        return obj

    def _commit(db: Session):
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, f"{entity}: duplicate value or invalid reference") from e

    @router.get("", response_model=Page[read_schema])
    def list_items(
        q: str | None = None,
        is_active: bool | None = None,
        page: int = Query(1, ge=1),
        size: int = Query(50, ge=1, le=200),
        db: Session = Depends(get_db),
        _: User = Depends(require(read_perm)),
    ):
        stmt = select(model)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(*[getattr(model, f).ilike(like) for f in search_fields]))
        if is_active is not None and hasattr(model, "is_active"):
            stmt = stmt.where(model.is_active == is_active)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        order = model.created_at if hasattr(model, "created_at") else model.id
        rows = db.scalars(stmt.order_by(order, model.id).offset((page - 1) * size).limit(size)).all()
        return {"items": rows, "total": total, "page": page, "size": size}

    @router.get("/{obj_id}", response_model=read_schema)
    def get_item(obj_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(require(read_perm))):
        return _get(db, obj_id)

    @router.post("", response_model=read_schema, status_code=status.HTTP_201_CREATED)
    def create_item(body: create_schema, db: Session = Depends(get_db), user: User = Depends(require(write_perm))):  # type: ignore[valid-type]
        obj = model(**body.model_dump())
        db.add(obj)
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, f"{entity}: duplicate value or invalid reference") from e
        write_audit(db, user, "create", entity, obj.id, after=row_to_dict(obj))
        _commit(db)
        return obj

    @router.patch("/{obj_id}", response_model=read_schema)
    def update_item(
        obj_id: uuid.UUID,
        body: update_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        user: User = Depends(require(write_perm)),
    ):
        obj = _get(db, obj_id)
        before = row_to_dict(obj)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, f"{entity}: duplicate value or invalid reference") from e
        write_audit(db, user, "update", entity, obj.id, before=before, after=row_to_dict(obj))
        _commit(db)
        return obj

    @router.delete("/{obj_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(obj_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require(write_perm))):
        obj = _get(db, obj_id)
        before = row_to_dict(obj)
        db.delete(obj)
        write_audit(db, user, "delete", entity, obj_id, before=before)
        _commit(db)  # 409 if other records still reference it; deactivate instead.

    return router
