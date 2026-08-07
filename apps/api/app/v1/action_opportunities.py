"""Deterministic, evidence-gated discovery for the priority-actions workbench."""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import (
    GeoActionOpportunity,
    GeoActionOpportunityEvidence,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)


RULE_VERSION = "opportunity.v1"
POSITIVE_BRAND_STATUSES = {"mentioned", "shortlisted", "recommended", "cited"}


def _fingerprint(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _source_url(source: object) -> str | None:
    if not isinstance(source, dict):
        return None
    value = source.get("url")
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value[:1500]
    return None


def _valid_real_evidence(row: GeoEvidence) -> bool:
    """Only evidence with a real answer, source URL and raw artifact can drive actions."""

    return bool(
        row.is_real_provider_evidence
        and row.answer_text.strip()
        and row.raw_artifact_uri
        and any(_source_url(source) for source in (row.source_items or []))
    )


def _task_for_evidence(db: Session, evidence_id: int, batch_id: int | None) -> GeoObservationTask | None:
    query = select(GeoObservationTask).where(
        GeoObservationTask.evidence_id == evidence_id,
        GeoObservationTask.status.in_(["completed", "succeeded"]),
    )
    if batch_id is not None:
        query = query.where(GeoObservationTask.batch_id == batch_id)
    return db.scalar(query.order_by(GeoObservationTask.id.desc()))


def _candidate_summary(workspace: GeoWorkspace, question: GeoQuestionPlan, absent: int, total: int) -> str:
    ratio = absent / total if total else 0
    return (
        f"在“{question.question_text}”的真实观测中，{workspace.brand_name}有 {absent}/{total} 个回答未被提及"
        f"（{ratio:.0%}）。建议围绕该问题补齐可引用的权威内容，并在复测中验证变化。"
    )


def discover_opportunities(
    db: Session,
    workspace: GeoWorkspace,
    *,
    batch_id: int | None = None,
    question_plan_ids: Iterable[int] | None = None,
    max_items: int = 50,
) -> list[GeoActionOpportunity]:
    """Materialize opportunities from the canonical evidence ledger.

    This function is intentionally synchronous and deterministic. It never calls an
    LLM or external search service; provider calls belong to the observation layer.
    """

    questions = {
        question.id: question
        for question in db.scalars(
            select(GeoQuestionPlan).where(
                GeoQuestionPlan.workspace_id == workspace.id,
                GeoQuestionPlan.active.is_(True),
            )
        )
    }
    selected_questions = set(question_plan_ids or questions.keys())
    evidence_rows = list(
        db.scalars(
            select(GeoEvidence)
            .where(
                GeoEvidence.workspace_id == workspace.id,
                GeoEvidence.is_real_provider_evidence.is_(True),
                GeoEvidence.question_plan_id.in_(selected_questions),
            )
            .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
        )
    )
    if batch_id is not None:
        # A batch is a hard scope boundary. Do not infer membership from timestamps.
        evidence_rows = [row for row in evidence_rows if _task_for_evidence(db, row.id, batch_id)]
    else:
        evidence_rows = [row for row in evidence_rows if _task_for_evidence(db, row.id, None)]
    evidence_rows = [row for row in evidence_rows if _valid_real_evidence(row)]

    grouped: dict[int, list[GeoEvidence]] = defaultdict(list)
    for row in evidence_rows:
        grouped[row.question_plan_id].append(row)

    batch = db.get(GeoObservationBatch, batch_id) if batch_id else None
    if batch is not None:
        # The current-batch view is a snapshot. Preserve historical rows for audit,
        # but mark opportunities not rediscovered in this batch as stale.
        for existing in db.scalars(
            select(GeoActionOpportunity).where(
                GeoActionOpportunity.workspace_id == workspace.id,
                GeoActionOpportunity.status.in_(["open", "selected"]),
            )
        ):
            existing.status = "stale"
    materialized: list[GeoActionOpportunity] = []
    for question_id, rows in grouped.items():
        question = questions.get(question_id)
        if question is None or len(rows) < 1:
            continue
        absent_rows = [row for row in rows if row.brand_status not in POSITIVE_BRAND_STATUSES]
        if not absent_rows:
            continue
        source_counts: Counter[str] = Counter(
            url
            for row in absent_rows
            for source in (row.source_items or [])
            if (url := _source_url(source))
        )
        top_source = source_counts.most_common(1)[0][0] if source_counts else None
        competitor_names = sorted(
            {
                str(item.get("name") or item.get("label") or item.get("brand") or "")
                for row in absent_rows
                for item in (row.competitor_positions or [])
                if isinstance(item, dict) and (item.get("name") or item.get("label") or item.get("brand"))
            }
        )
        absent_ratio = len(absent_rows) / len(rows)
        evidence_strength = min(1.0, len(rows) / 6) * (0.8 if source_counts else 0.4)
        score = min(
            100.0,
            question.importance * 12 + absent_ratio * 58 + min(len(competitor_names), 3) * 6 + evidence_strength * 12,
        )
        priority = "high" if score >= 72 else "medium" if score >= 48 else "low"
        opportunity_type = "competitor_gap" if competitor_names else "brand_absent"
        fingerprint = _fingerprint(
            workspace.id,
            question.id,
            opportunity_type,
            top_source or "no-source",
            RULE_VERSION,
        )
        title = (
            f"补齐“{question.question_text[:62]}”中的品牌答案"
            if opportunity_type == "brand_absent"
            else f"在“{question.question_text[:54]}”中建立品牌对比依据"
        )
        opportunity = db.scalar(
            select(GeoActionOpportunity).where(
                GeoActionOpportunity.workspace_id == workspace.id,
                GeoActionOpportunity.fingerprint == fingerprint,
            )
        )
        scope_snapshot = {
            "batch_id": batch.id if batch else None,
            "batch_status": batch.status if batch else None,
            "question_plan_id": question.id,
            "question": question.question_text,
            "evidence_count": len(rows),
            "absent_count": len(absent_rows),
            "absent_ratio": round(absent_ratio, 4),
            "competitors": competitor_names[:8],
            "top_source_url": top_source,
            "eligibility": "real_answer+source_url+raw_artifact+completed_task",
        }
        if opportunity is None:
            opportunity = GeoActionOpportunity(
                workspace_id=workspace.id,
                fingerprint=fingerprint,
                opportunity_type=opportunity_type,
                title=title,
                summary=_candidate_summary(workspace, question, len(absent_rows), len(rows)),
                priority_score=round(score, 2),
                priority_label=priority,
                evidence_strength=round(evidence_strength, 4),
                source_gap_type="missing_brand_citation" if top_source else "missing_authority_source",
                recommended_asset_type="article",
                recommended_platforms=["zhihu", "official_site", "wechat"],
                scope_snapshot=scope_snapshot,
                rule_version=RULE_VERSION,
                status="open",
                first_seen_batch_id=batch.id if batch else None,
                latest_seen_batch_id=batch.id if batch else None,
            )
            db.add(opportunity)
            db.flush()
        else:
            opportunity.title = title
            opportunity.summary = _candidate_summary(workspace, question, len(absent_rows), len(rows))
            opportunity.priority_score = round(score, 2)
            opportunity.priority_label = priority
            opportunity.evidence_strength = round(evidence_strength, 4)
            opportunity.scope_snapshot = scope_snapshot
            opportunity.latest_seen_batch_id = batch.id if batch else opportunity.latest_seen_batch_id
            if opportunity.status == "stale":
                opportunity.status = "open"

        for row in absent_rows[:12]:
            task = _task_for_evidence(db, row.id, batch_id)
            first_source = next((_source_url(source) for source in (row.source_items or []) if _source_url(source)), None)
            exists = db.scalar(
                select(GeoActionOpportunityEvidence).where(
                    GeoActionOpportunityEvidence.opportunity_id == opportunity.id,
                    GeoActionOpportunityEvidence.evidence_id == row.id,
                )
            )
            if exists:
                continue
            db.add(
                GeoActionOpportunityEvidence(
                    opportunity_id=opportunity.id,
                    workspace_id=workspace.id,
                    batch_id=task.batch_id if task else batch_id,
                    observation_task_id=task.id if task else None,
                    evidence_id=row.id,
                    question_plan_id=row.question_plan_id,
                    provider_id=task.provider_id if task else None,
                    model_key=row.model_key,
                    signal_type=opportunity_type,
                    signal_value={
                        "brand_status": row.brand_status,
                        "competitors": row.competitor_positions or [],
                        "captured_at": row.captured_at.isoformat(),
                    },
                    evidence_hash=row.answer_hash,
                    source_url=first_source,
                )
            )
        materialized.append(opportunity)

    db.commit()
    return sorted(materialized, key=lambda item: (-item.priority_score, item.id))[:max_items]
