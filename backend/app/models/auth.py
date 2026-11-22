import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class Permission(IdMixin, Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(80), unique=True)  # "module:action"
    description: Mapped[str | None] = mapped_column(String(255))


class Role(IdMixin, Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(255))
    # Global-scope roles see every project; others only projects they are granted.
    is_global_scope: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list[Permission]] = relationship(secondary="role_permissions", lazy="selectin")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    role: Mapped[Role] = relationship(lazy="joined")

    @property
    def permission_codes(self) -> set[str]:
        return {p.code for p in self.role.permissions}


class UserProjectAccess(Base):
    __tablename__ = "user_project_access"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
