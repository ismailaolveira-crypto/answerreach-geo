from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@router.get("/ready")
def readiness_check(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready", "database": "reachable"}
