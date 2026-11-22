import uuid
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin


class Customer(IdMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Department(IdMixin, TimestampMixin, Base):
    __tablename__ = "departments"
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Location(IdMixin, TimestampMixin, Base):
    __tablename__ = "locations"
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Resource(IdMixin, TimestampMixin, Base):
    """Employee / consultant. Optionally linked to a login user."""

    __tablename__ = "resources"
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StatusConfig(IdMixin, TimestampMixin, Base):
    """Per-entity status dictionary. `category` drives KPI logic (done / in progress / ...)."""

    __tablename__ = "status_configs"
    __table_args__ = (
        UniqueConstraint("entity_type", "code"),
        CheckConstraint("category in ('not_started','in_progress','done','cancelled','blocked')", name="category"),
    )
    entity_type: Mapped[str] = mapped_column(String(50))
    code: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20))
    color: Mapped[str | None] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30), default="Planned")
    start_date: Mapped[date | None] = mapped_column(Date)
    target_go_live: Mapped[date | None] = mapped_column(Date)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # an item is "delayed" only after its date + this many days (rule still to be decided by the business)
    delay_grace_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    products: Mapped[list["ProjectProduct"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    sites: Mapped[list["ProjectSite"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


class ProjectProduct(IdMixin, Base):
    __tablename__ = "project_products"
    __table_args__ = (UniqueConstraint("project_id", "product_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    go_live_date: Mapped[date | None] = mapped_column(Date)
    project: Mapped[Project] = relationship(back_populates="products")
    product: Mapped[Product] = relationship(lazy="joined")


class ProjectSite(IdMixin, Base):
    """A location/entity where a project is implemented (e.g. Decotex, Arena)."""

    __tablename__ = "project_sites"
    __table_args__ = (UniqueConstraint("project_id", "location_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    entity_name: Mapped[str | None] = mapped_column(String(200))
    project: Mapped[Project] = relationship(back_populates="sites")
    location: Mapped[Location] = relationship(lazy="joined")
