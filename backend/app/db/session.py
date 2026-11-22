from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(_settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
if _settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless enabled
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


SessionLocal =sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
