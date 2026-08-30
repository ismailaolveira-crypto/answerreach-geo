from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app import models  # noqa: F401
from app.core.config import get_settings
from app.db.session import Base, SessionLocal, engine
from app.services.article_sync_adapter import shutdown_article_sync_runtime
from app.services.workspace_access import backfill_legacy_workspace_memberships


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,79}$")


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

    @app.middleware("http")
    async def request_identity(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "").strip()
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

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
