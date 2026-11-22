import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import row_to_dict, write_audit
from app.core.deps import get_db, require
from app.models import AuditLog, CustomFieldDefinition, User
from app.schemas.common import ORMModel, Page

audit_router = APIRouter()
custom_fields_router = APIRouter()


class AuditOut(ORMModel):
    id: uuid.UUID
    at: datetime
    user_id: Optional[uuid.UUID]
    user_email: Optional[str]
    action: str
    entity_type: str
    entity_id: Optional[str]
    before: Optional[dict]
    after: Optional[dict]


@audit_router.get("", response_model=Page[AuditOut])
def list_audit(
    entity_type: str | None = None,
    entity_id: str | None = None,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require("audit:read")),
):
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.at.desc(), AuditLog.id).offset((page - 1) * size).limit(size)).all()
    return {"items": rows, "total": total, "page": page, "size": size}


# ---- flex fields: 5 dropdown + 5 date + 5 text per entity, options per customer ----
class FlexCreate(ORMModel):
    customer_id: Optional[uuid.UUID] = None
    entity_type: str = Field(min_length=1, max_length=50)
    field_type: Literal["dropdown", "date", "text"]
    slot: int = Field(ge=1, le=5)
    label: str = Field(min_length=1, max_length=100)
    options: Optional[list[str]] = None
    is_required: bool = False

    @model_validator(mode="after")
    def _options_rules(self):
        if self.field_type == "dropdown":
            if not self.options or any(not o.strip() for o in self.options):
                raise ValueError("dropdown fields need a non-empty list of options")
        elif self.options:
            raise ValueError("options are only valid for dropdown fields")
        return self


class FlexRead(FlexCreate):
    id: uuid.UUID


@custom_fields_router.get("/entities")
def flex_entities(_: User = Depends(require("master:read"))):
    """The record types that can carry flex fields, for the screen that defines them."""
    from app.api.flex_values import ENTITY_LABELS  # noqa: PLC0415

    return [{"value": k, "label": v} for k, v in ENTITY_LABELS.items()]


@custom_fields_router.get("", response_model=list[FlexRead])
def list_flex(
    entity_type: str | None = None,
    customer_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require("master:read")),
):
    stmt = select(CustomFieldDefinition)
    if entity_type:
        stmt = stmt.where(CustomFieldDefinition.entity_type == entity_type)
    if customer_id:
        stmt = stmt.where(CustomFieldDefinition.customer_id == customer_id)
    return db.scalars(stmt.order_by(CustomFieldDefinition.field_type, CustomFieldDefinition.slot)).all()


@custom_fields_router.post("", response_model=FlexRead, status_code=status.HTTP_201_CREATED)
def create_flex(body: FlexCreate, db: Session = Depends(get_db), user: User = Depends(require("custom_fields:write"))):
    from app.api.flex_values import ENTITY_LABELS  # noqa: PLC0415

    if body.entity_type not in ENTITY_LABELS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Flex fields are not available for '{body.entity_type}'. Choose one of: {', '.join(ENTITY_LABELS)}")
    obj = CustomFieldDefinition(**body.model_dump())
    db.add(obj)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That slot is already used, or customer is unknown") from e
    write_audit(db, user, "create", "custom_field_definition", obj.id, after=row_to_dict(obj))
    db.commit()
    return obj


@custom_fields_router.patch("/{field_id}", response_model=FlexRead)
def update_flex_label(
    field_id: uuid.UUID,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require("custom_fields:write")),
):
    obj = db.get(CustomFieldDefinition, field_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flex field not found")
    allowed = {"label", "options", "is_required"}
    if not set(body) <= allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Only {sorted(allowed)} can be changed")
    before = row_to_dict(obj)
    merged = {
        "customer_id": obj.customer_id, "entity_type": obj.entity_type, "field_type": obj.field_type,
        "slot": obj.slot, "label": obj.label, "options": obj.options, "is_required": obj.is_required, **body,
    }
    try:
        valid = FlexCreate(**merged)  # re-validate the merged result before touching the row
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors(include_url=False, include_context=False))
    obj.label, obj.options, obj.is_required = valid.label, valid.options, valid.is_required
    write_audit(db, user, "update", "custom_field_definition", obj.id, before=before, after=row_to_dict(obj))
    db.commit()
    return obj


@custom_fields_router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flex(field_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("custom_fields:write"))):
    obj = db.get(CustomFieldDefinition, field_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flex field not found")
    write_audit(db, user, "delete", "custom_field_definition", obj.id, before=row_to_dict(obj))
    db.delete(obj)  # values cascade
    db.commit()
