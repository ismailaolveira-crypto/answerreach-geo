from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app import models  # noqa: F401
from app.core.config import get_settings
from app.db.session import Base, SessionLocal, engine
from app.services.article_sync_adapter import shutdown_article_sync_runtime
from app.services.workspace_access import backfill_legacy_workspace_memberships


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_deployment()
    if settings.auto_create_tables:
        if settings.is_production:
            raise RuntimeError(
                "AUTO_CREATE_TABLES must be disabled in production. Run Alembic migrations instead."
            )
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            backfill_legacy_workspace_memberships(db)
    try:
        yield
    finally:
        shutdown_article_sync_runtime()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    return app


app = create_app()
