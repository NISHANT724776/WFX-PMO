from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import AuditLog, User

_REDACT = {"password_hash"}


def row_to_dict(obj: Any) -> dict:
    data = {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key not in _REDACT}
    return jsonable_encoder(data)


def write_audit(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    before: dict | None = None,
    after: dict | None = None,
    email: str | None = None,
) -> None:
    """Adds to the caller's session so the audit row commits atomically with the change."""
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else email,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=before,
            after=after,
        )
    )
