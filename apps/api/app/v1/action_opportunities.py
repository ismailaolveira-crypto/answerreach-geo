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
    GeoWebsiteAudit,
    GeoWorkspace,
)


RULE_VERSION = "opportunity.v1"
WEBSITE_RULE_VERSION = "website-opportunity.v1"
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


def valid_action_evidence(row: GeoEvidence) -> bool:
    """Apply the complete product evidence gate before an answer can drive work."""

    environment = row.sampling_environment or {}
    return bool(
        row.is_real_provider_evidence
        and row.answer_text.strip()
        and row.raw_artifact_uri
        and environment.get("search_verified") is True
        and int(environment.get("search_event_count") or 0) >= 1
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


def materialize_website_opportunity(
    db: Session,
    workspace: GeoWorkspace,
    audit: GeoWebsiteAudit,
) -> GeoActionOpportunity | None:
    """Turn one immutable website audit into a deduplicated, source-labelled opportunity.

    Website audits are deliberately not inserted into ``GeoEvidence``: they are public-site
    captures, not model observations. Their raw hash, artifact manifest and findings remain in
    the audit row and are carried by reference in the opportunity scope.
    """

    open_rows = list(
        db.scalars(
            select(GeoActionOpportunity).where(
                GeoActionOpportunity.workspace_id == workspace.id,
                GeoActionOpportunity.opportunity_type == "website_citation_readiness",
                GeoActionOpportunity.status == "open",
            )
        )
    )
    findings = [item for item in (audit.findings or []) if isinstance(item, dict)]
    finding_codes = sorted(
        {
            str(item.get("code") or "").strip()
            for item in findings
            if str(item.get("code") or "").strip()
        }
    )
    if audit.status == "ready" or not finding_codes:
        for row in open_rows:
            row.status = "stale"
        return None

    fingerprint = _fingerprint(
        workspace.id,
        "website_citation_readiness",
        finding_codes,
        WEBSITE_RULE_VERSION,
    )
    for row in open_rows:
        if row.fingerprint != fingerprint:
            row.status = "stale"

    opportunity = db.scalar(
        select(GeoActionOpportunity).where(
            GeoActionOpportunity.workspace_id == workspace.id,
            GeoActionOpportunity.fingerprint == fingerprint,
        )
    )
    blocked = audit.status == "blocked"
    client_shell = "client_rendering_required" in finding_codes
    missing_body = any(
        code in finding_codes
        for code in {"server_visible_content_missing", "server_visible_content_too_short"}
    )
    if blocked:
        title = "恢复官网公开可访问性并重新检查"
        asset_type = "article"
    elif client_shell or missing_body:
        title = "补齐官网服务端可读的产品答案"
        asset_type = "article"
    else:
        title = "补齐官网可抓取、可理解的引用信息"
        asset_type = "article"

    priority_score = round(max(0.0, min(100.0, 100.0 - float(audit.score))), 2)
    priority = "high" if blocked or priority_score >= 60 else "medium" if priority_score >= 35 else "low"
    evidence_strength = 1.0 if audit.raw_html_sha256 and audit.artifact_manifest else 0.55
    top_findings = [str(item.get("title") or item.get("code") or "").strip() for item in findings[:3]]
    summary = (
        f"官网审计 #{audit.id} 得分 {round(audit.score)}/100，"
        f"确认 {len(finding_codes)} 项公开页面问题：{'、'.join(top_findings)}。"
        "该结论来自官网原始响应，不是模型回答或 GEO 提及结果。"
    )
    scope_snapshot = {
        "source_type": "website_audit",
        "website_audit_id": audit.id,
        "website_url": audit.final_url or audit.requested_url,
        "website_audit_status": audit.status,
        "website_audit_score": audit.score,
        "website_audit_version": audit.audit_version,
        "raw_html_sha256": audit.raw_html_sha256,
        "raw_html_size": audit.raw_html_size,
        "artifact_manifest": audit.artifact_manifest,
        "finding_codes": finding_codes,
        "findings": findings,
        "question": "官网是否便于搜索引擎和 AI 系统抓取、理解与引用？",
        "recommended_carrier": "官网服务端正文与结构化信息",
        "eligibility": "public_response+raw_artifact_manifest+immutable_audit",
    }
    values = {
        "opportunity_type": "website_citation_readiness",
        "title": title,
        "summary": summary,
        "priority_score": priority_score,
        "priority_label": priority,
        "evidence_strength": evidence_strength,
        "source_gap_type": "website_citation_readiness",
        "recommended_asset_type": asset_type,
        "recommended_platforms": ["official_site"],
        "scope_snapshot": scope_snapshot,
        "rule_version": WEBSITE_RULE_VERSION,
        "status": "open",
    }
    if opportunity is None:
        opportunity = GeoActionOpportunity(
            workspace_id=workspace.id,
            fingerprint=fingerprint,
            **values,
        )
        db.add(opportunity)
        db.flush()
    elif opportunity.status not in {"selected", "completed", "dismissed"}:
        for key, value in values.items():
            setattr(opportunity, key, value)
    return opportunity


def discover_opportunities(
    db: Session,
    workspace: GeoWorkspace,
    *,
    batch_id: int | None = None,
    question_plan_ids: Iterable[int] | None = None,
    model_keys: Iterable[str] | None = None,
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
    selected_models = tuple(sorted({value.strip() for value in (model_keys or []) if value.strip()}))
    evidence_rows = list(
        db.scalars(
            select(GeoEvidence)
            .where(
                GeoEvidence.workspace_id == workspace.id,
                GeoEvidence.is_real_provider_evidence.is_(True),
                GeoEvidence.question_plan_id.in_(selected_questions),
                *([GeoEvidence.model_key.in_(selected_models)] if selected_models else []),
            )
            .order_by(GeoEvidence.captured_at.desc(), GeoEvidence.id.desc())
        )
    )
    if batch_id is not None:
        # A batch is a hard scope boundary. Do not infer membership from timestamps.
        evidence_rows = [row for row in evidence_rows if _task_for_evidence(db, row.id, batch_id)]
    else:
        evidence_rows = [row for row in evidence_rows if _task_for_evidence(db, row.id, None)]
    evidence_rows = [row for row in evidence_rows if valid_action_evidence(row)]

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
                GeoActionOpportunity.status == "open",
            )
        ):
            scope = existing.scope_snapshot or {}
            scope_models = tuple(sorted(scope.get("model_keys") or []))
            if (
                int(scope.get("question_plan_id") or 0) in selected_questions
                and scope_models == selected_models
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
            selected_models or ("all_models",),
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
            "model_keys": list(selected_models),
            "eligibility": (
                "completed_task+real_answer+search_event+source_url+raw_artifact"
            ),
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
