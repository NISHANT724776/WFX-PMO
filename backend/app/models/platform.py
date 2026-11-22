import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utcnow

FLEX_TYPES = ("dropdown", "date", "text")
FLEX_SLOTS_PER_TYPE = 5


class CustomFieldDefinition(IdMixin, TimestampMixin, Base):
    """Flex field: 5 dropdown + 5 date + 5 text slots per entity; options per customer."""

    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint("customer_id", "entity_type", "field_type", "slot"),
        CheckConstraint("slot between 1 and 5", name="slot_range"),
        CheckConstraint("field_type in ('dropdown','date','text')", name="field_type"),
        # A plain UNIQUE ignores NULL customer_id, so global (no-customer) fields need their own index.
        Index(
            "uq_cfd_global_slot", "entity_type", "field_type", "slot", unique=True,
            sqlite_where=text("customer_id IS NULL"), postgresql_where=text("customer_id IS NULL"),
        ),
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    field_type: Mapped[str] = mapped_column(String(20))
    slot: Mapped[int] = mapped_column()
    label: Mapped[str] = mapped_column(String(100))
    options: Mapped[list | None] = mapped_column(JSON)  # dropdown choices
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomFieldValue(IdMixin, TimestampMixin, Base):
    __tablename__ = "custom_field_values"
    __table_args__ = (UniqueConstraint("definition_id", "entity_id"), Index("ix_cfv_entity", "entity_type", "entity_id"))
    definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("custom_field_definitions.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_date: Mapped[date | None] = mapped_column(Date)


class AuditLog(IdMixin, Base):
    """Append-only. Never updated or deleted by application code."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    user_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(40))  # create | update | delete | login | login_failed ...
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
