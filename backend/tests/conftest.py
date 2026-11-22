import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="wfx_test_")
os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    SECRET_KEY="test-secret-test-secret-test-secret-123",
    ADMIN_EMAIL="admin@example.com",
    ADMIN_PASSWORD="Admin-Test-Pass-1",
    AUTO_CREATE_TABLES="false",
    SEED_ON_STARTUP="false",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.seed import seed  # noqa: E402
from sqlalchemy import select  # noqa: E402

PASSWORD = "Some-Long-Password-1"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email, password=PASSWORD):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client):
    return _login(client, "admin@example.com", "Admin-Test-Pass-1")


@pytest.fixture
def make_user(client):
    def _make(role_code: str, email: str | None = None):
        email = email or f"{role_code}@example.com"
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.code == role_code))
            u = User(email=email, full_name=role_code, password_hash=hash_password(PASSWORD), role_id=role.id)
            db.add(u)
            db.commit()
            uid = str(u.id)
        return uid, _login(client, email)

    return _make
