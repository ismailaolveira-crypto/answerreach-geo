"""Verified brand-fact ledger helpers shared by routes and Agent context."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.models.cleanroom_v1 import GeoBrandFact


BRAND_FACT_VERIFICATION_ACTION = "workspace.brand_fact.source_verified"
BRAND_FACT_VERIFICATION_FAILED_ACTION = "workspace.brand_fact.source_verification_failed"


def statement_fingerprint(statement: str) -> str:
    return sha256(statement.strip().encode("utf-8")).hexdigest()


def brand_fact_source_verification(
    db: Session,
    fact: GeoBrandFact,
) -> dict | None:
    """Return the latest proof only when it still matches the current fact."""

    log = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action.in_(
                [BRAND_FACT_VERIFICATION_ACTION, BRAND_FACT_VERIFICATION_FAILED_ACTION]
            ),
            AuditLog.resource_type == "geo_brand_fact",
            AuditLog.resource_id == fact.id,
        )
        .order_by(AuditLog.id.desc())
    )
    if log is None:
        return None
    if log.action != BRAND_FACT_VERIFICATION_ACTION:
        return None
    detail = log.detail_json or {}
    verification = detail.get("verification")
    if not isinstance(verification, dict):
        return None
    if str(detail.get("source_url") or "") != str(fact.source_url or ""):
        return None
    if str(detail.get("statement_sha256") or "") != statement_fingerprint(fact.statement):
        return None
    if verification.get("status") != "source_and_statement_verified":
        return None
    return verification


def brand_fact_source_verification_failure(
    db: Session,
    fact: GeoBrandFact,
) -> dict | None:
    """Return the latest failed attempt when it still matches the current fact."""

    log = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action.in_(
                [BRAND_FACT_VERIFICATION_ACTION, BRAND_FACT_VERIFICATION_FAILED_ACTION]
            ),
            AuditLog.resource_type == "geo_brand_fact",
            AuditLog.resource_id == fact.id,
        )
        .order_by(AuditLog.id.desc())
    )
    if log is None or log.action != BRAND_FACT_VERIFICATION_FAILED_ACTION:
        return None
    detail = log.detail_json or {}
    verification = detail.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "failed":
        return None
    if str(detail.get("source_url") or "") != str(fact.source_url or ""):
        return None
    if str(detail.get("statement_sha256") or "") != statement_fingerprint(fact.statement):
        return None
    return {
        "status": "failed",
        "http_status": int(verification.get("http_status") or 0),
        "detail": str(verification.get("detail") or "公开来源核验失败。"),
        "attempted_at": log.created_at.isoformat(),
    }


def verified_active_brand_facts(db: Session, workspace_id: int) -> list[GeoBrandFact]:
    candidates = list(
        db.scalars(
            select(GeoBrandFact)
            .where(
                GeoBrandFact.workspace_id == workspace_id,
                GeoBrandFact.status == "active",
                GeoBrandFact.source_url.is_not(None),
            )
            .order_by(GeoBrandFact.id)
        )
    )
    return [fact for fact in candidates if brand_fact_source_verification(db, fact)]


def brand_fact_read(db: Session, fact: GeoBrandFact) -> dict:
    return {
        "id": fact.id,
        "workspace_id": fact.workspace_id,
        "title": fact.title,
        "statement": fact.statement,
        "source_url": fact.source_url,
        "status": fact.status,
        "source_verification": brand_fact_source_verification(db, fact),
        "source_verification_failure": brand_fact_source_verification_failure(db, fact),
    }
