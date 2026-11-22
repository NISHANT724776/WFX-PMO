import uuid
from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import User, UserProjectAccess

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    sub = decode_access_token(creds.credentials)
    if sub is None:
        raise unauthorized
    try:
        user = db.get(User, uuid.UUID(sub))
    except ValueError:
        raise unauthorized
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require(*perms: str):
    """Backend permission gate. The frontend hiding buttons is never the control."""

    def dep(user: User = Depends(current_user)) -> User:
        missing = [p for p in perms if p not in user.permission_codes]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {', '.join(missing)}")
        return user

    return dep


def accessible_project_ids(db: Session, user: User) -> set[uuid.UUID] | None:
    """None = all projects (global-scope role); otherwise the explicit grant set."""
    if user.role.is_global_scope:
        return None
    rows = db.query(UserProjectAccess.project_id).filter(UserProjectAccess.user_id == user.id).all()
    return {r[0] for r in rows}


def ensure_project_access(db: Session, user: User, project_id: uuid.UUID) -> None:
    allowed = accessible_project_ids(db, user)
    if allowed is not None and project_id not in allowed:
        # 404, not 403: do not reveal that the project exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
