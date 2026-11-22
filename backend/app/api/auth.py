from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import current_user, get_db
from app.core.security import create_access_token, verify_password
from app.models import User

router = APIRouter()


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_global_scope: bool
    permissions: list[str]


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        write_audit(db, None, "login_failed", "user", None, email=body.email.lower())
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    write_audit(db, user, "login", "user", user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role.code,
        is_global_scope=user.role.is_global_scope,
        permissions=sorted(user.permission_codes),
    )
