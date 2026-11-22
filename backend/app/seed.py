"""Idempotent bootstrap: permissions, roles, default status dictionary, optional super admin."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import PERMISSIONS, ROLE_MATRIX
from app.core.security import MIN_PASSWORD_LENGTH, hash_password
from app.models import Permission, Role, StatusConfig, User

log = logging.getLogger(__name__)

# (code, label, category, color) -- generic defaults; editable in Status Configuration.
DEFAULT_STATUSES = [
    ("not_started", "Not Started", "not_started", "#64748b"),
    ("in_progress", "In Progress", "in_progress", "#d97706"),
    ("done", "Done", "done", "#16a34a"),
    ("blocked", "Blocked", "blocked", "#dc2626"),
    ("cancelled", "Cancelled", "cancelled", "#94a3b8"),
]
STATUS_ENTITIES = ["work_item", "milestone", "delivery_item", "dependency", "helpdesk_item", "integration_item", "report_item"]
# approval gates have their own, editable states (Status Configuration). The category decides what counts as approved.
GATE_STATUSES = [
    ("not_submitted", "Not submitted", "not_started", "#64748b"),
    ("submitted", "Submitted", "in_progress", "#d97706"),
    ("under_review", "Under review", "in_progress", "#d97706"),
    ("changes_requested", "Changes requested", "blocked", "#dc2626"),
    ("approved", "Approved", "done", "#16a34a"),
    ("rejected", "Rejected", "blocked", "#dc2626"),
]


def seed(db: Session) -> None:
    perms = {p.code: p for p in db.scalars(select(Permission))}
    for code, desc in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=desc)
            db.add(perms[code])
    roles = {r.code: r for r in db.scalars(select(Role))}
    for code, (name, is_global, plist) in ROLE_MATRIX.items():
        role = roles.get(code)
        if role is None:
            role = roles[code] = Role(code=code, name=name, is_global_scope=is_global)
            db.add(role)
        role.name, role.is_global_scope = name, is_global
        role.permissions = [perms[p] for p in plist]

    existing = {(s.entity_type, s.code) for s in db.scalars(select(StatusConfig))}
    for entity in STATUS_ENTITIES:
        for i, (code, label, cat, color) in enumerate(DEFAULT_STATUSES):
            if (entity, code) not in existing:
                db.add(StatusConfig(entity_type=entity, code=code, label=label, category=cat, color=color, sort_order=i))
    for i, (code, label, cat, color) in enumerate(GATE_STATUSES):
        if ("approval_gate", code) not in existing:
            db.add(StatusConfig(entity_type="approval_gate", code=code, label=label, category=cat, color=color, sort_order=i))
    db.flush()

    s = get_settings()
    if s.admin_password:
        if len(s.admin_password) < MIN_PASSWORD_LENGTH:
            raise RuntimeError(f"ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters")
        email = s.admin_email.lower()
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(email=email, full_name="Super Admin", password_hash=hash_password(s.admin_password),
                        role_id=roles["super_admin"].id))
            log.info("Created bootstrap super admin %s", email)
    else:
        log.warning("ADMIN_PASSWORD not set: no bootstrap admin created")
    db.commit()
