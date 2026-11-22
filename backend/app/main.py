from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api
from app.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
import app.models  # noqa: F401  (register tables)
from app.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.auto_create_tables:
        Base.metadata.create_all(engine)
    if s.seed_on_startup:
        with SessionLocal() as db:
            seed(db)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="WFX PMO Platform API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(api)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
