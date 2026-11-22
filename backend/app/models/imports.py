import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin, utcnow


class MappingTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "mapping_templates"
    name: Mapped[str] = mapped_column(String(150), unique=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    definition: Mapped[dict] = mapped_column(JSON)  # {"sheets": [...]}
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    use_count: Mapped[int] = mapped_column(Integer, default=0)


class ImportBatch(IdMixin, TimestampMixin, Base):
    """One uploaded file and everything derived from it. Doubles as the uploaded_files record."""

    __tablename__ = "import_batches"
    filename: Mapped[str] = mapped_column(String(300))
    stored_name: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    ext: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded|analyzing|ready|failed|committed|rolled_back
    error: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    purpose: Mapped[str | None] = mapped_column(String(30))  # new_tracker | update | snapshot
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mapping_templates.id"))
    meta: Mapped[dict | None] = mapped_column(JSON)  # relationships, workbook warnings
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    commit_summary: Mapped[dict | None] = mapped_column(JSON)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sheets: Mapped[list["UploadedSheet"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="UploadedSheet.position"
    )


class UploadedSheet(IdMixin, Base):
    __tablename__ = "uploaded_sheets"
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(10), default="visible")
    n_rows: Mapped[int] = mapped_column(Integer, default=0)
    n_cols: Mapped[int] = mapped_column(Integer, default=0)
    classification: Mapped[str] = mapped_column(String(40), default="unknown")
    class_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    entity: Mapped[str | None] = mapped_column(String(40))  # target entity chosen/suggested
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # user-editable: header_row, product_map, value_maps, gate_type
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    profile: Mapped[dict | None] = mapped_column(JSON)  # structure stats, header candidates, section rows
    batch: Mapped[ImportBatch] = relationship(back_populates="sheets")
    columns: Mapped[list["DetectedColumn"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="DetectedColumn.index"
    )


class DetectedColumn(IdMixin, Base):
    __tablename__ = "detected_columns"
    sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploaded_sheets.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    letter: Mapped[str] = mapped_column(String(5))
    header: Mapped[str] = mapped_column(String(300))
    group_label: Mapped[str | None] = mapped_column(String(200))
    inferred_type: Mapped[str] = mapped_column(String(20))
    profile: Mapped[dict] = mapped_column(JSON)
    sheet: Mapped[UploadedSheet] = relationship(back_populates="columns")
    mapping: Mapped["ColumnMapping | None"] = relationship(
        back_populates="column", cascade="all, delete-orphan", uselist=False
    )


class ColumnMapping(IdMixin, Base):
    __tablename__ = "column_mappings"
    __table_args__ = (UniqueConstraint("column_id"),)
    sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploaded_sheets.id", ondelete="CASCADE"), index=True)
    column_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detected_columns.id", ondelete="CASCADE"))
    target_field: Mapped[str | None] = mapped_column(String(60))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[str] = mapped_column(String(10), default="none")  # high|medium|low|none
    status: Mapped[str] = mapped_column(String(12), default="suggested")  # suggested|confirmed|ignored|unmapped
    source: Mapped[str] = mapped_column(String(10), default="auto")  # auto|history|template|user
    alternatives: Mapped[list | None] = mapped_column(JSON)
    column: Mapped[DetectedColumn] = relationship(back_populates="mapping")


class ValidationIssue(IdMixin, Base):
    __tablename__ = "validation_errors"
    __table_args__ = (Index("ix_val_batch_sheet", "batch_id", "sheet_id"),)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("uploaded_sheets.id", ondelete="CASCADE"))
    row_number: Mapped[int | None] = mapped_column(Integer)  # 1-based Excel row; None = sheet-level
    column_header: Mapped[str | None] = mapped_column(String(300))
    field: Mapped[str | None] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(10))  # error | warning | info
    code: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    raw_value: Mapped[str | None] = mapped_column(Text)
    rejects_row: Mapped[bool] = mapped_column(Boolean, default=False)


class ImportRowReference(IdMixin, Base):
    """Provenance: which source row produced which canonical record."""

    __tablename__ = "import_row_references"
    __table_args__ = (Index("ix_irr_entity", "entity_type", "entity_id"),)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploaded_sheets.id", ondelete="CASCADE"))
    source_row: Mapped[int] = mapped_column(Integer)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(10))  # created | updated | skipped
    seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # order of writes within the batch (rollback undoes newest first)
    before: Mapped[dict | None] = mapped_column(JSON)  # prior values when updated (enables rollback)
    row_stamp: Mapped[str | None] = mapped_column(String(40))  # record updated_at right after commit
    raw: Mapped[dict | None] = mapped_column(JSON)  # original cell values by header
