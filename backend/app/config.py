from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_KEY = "dev-only-change-me-dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")

    environment: str = "development"  # development | test | production
    database_url: str = "sqlite:///./dev.db"
    secret_key: str = _INSECURE_KEY
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:3000"
    upload_dir: str = ""  # default: backend/uploads
    max_upload_mb: int = 25

    # Dev convenience only. Production uses Alembic migrations.
    auto_create_tables: bool = False
    seed_on_startup: bool = True
    # Bootstrap super admin. No default password: if empty, no admin is created.
    admin_email: str = "admin@example.com"
    admin_password: str = ""

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        """Hosted databases (Neon, Render, Supabase) hand out postgres:// or postgresql:// links; the app uses the psycopg 3 driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @model_validator(mode="after")
    def _guard_production(self):
        if self.environment == "production":
            if self.secret_key == _INSECURE_KEY or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be set to a strong value in production")
            if self.auto_create_tables:
                raise ValueError("AUTO_CREATE_TABLES must be false in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
