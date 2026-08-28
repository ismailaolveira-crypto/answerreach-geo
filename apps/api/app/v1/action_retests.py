"""Deterministic, evidence-gated metrics for comparable priority-action retests."""

from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import GeoEvidence, GeoObservationBatch, GeoObservationTask


POSITIVE_STATUSES = {"mentioned", "shortlisted", "recommended", "cited"}
STATUS_WEIGHT = {
    "absent": 0,
    "negative": -1,
    "mentioned": 1,
    "shortlisted": 2,
    "cited": 2,
    "recommended": 3,
}


def _source_urls(evidence: GeoEvidence) -> list[str]:
    return [
        str(item.get("url"))
        for item in (evidence.source_items or [])
        if isinstance(item, dict)
        and str(item.get("url") or "").startswith(("http://", "https://"))
    ]


def _eligibility_reason(task: GeoObservationTask, evidence: GeoEvidence | None) -> str | None:
    if task.status not in {"completed", "succeeded"}:
        return "task_not_completed"
    if evidence is None:
        return "evidence_missing"
    if not evidence.is_real_provider_evidence:
        return "not_real_provider_evidence"
    if not evidence.answer_text.strip():
        return "answer_missing"
    environment = evidence.sampling_environment or {}
    if environment.get("search_verified") is not True:
        return "search_not_verified"
    if int(environment.get("search_event_count") or 0) < 1:
        return "search_event_missing"
    if not _source_urls(evidence):
        return "source_url_missing"
    if not evidence.raw_artifact_uri:
        return "raw_artifact_missing"
    return None


def build_batch_metrics(
    db: Session,
    batch: GeoObservationBatch,
    *,
    question_plan_id: int | None = None,
    question_plan_ids: list[int] | None = None,
    provider_ids: list[int] | None = None,
) -> dict:
    task_query = select(GeoObservationTask).where(GeoObservationTask.batch_id == batch.id)
    selected_question_ids = set(question_plan_ids or [])
    if question_plan_id is not None:
        selected_question_ids.add(question_plan_id)
    if selected_question_ids:
        task_query = task_query.where(GeoObservationTask.question_plan_id.in_(selected_question_ids))
    if provider_ids is not None:
        task_query = task_query.where(GeoObservationTask.provider_id.in_(provider_ids))
    tasks = list(
        db.scalars(
            task_query.order_by(GeoObservationTask.id)
        )
    )
    evidence_ids = [task.evidence_id for task in tasks if task.evidence_id]
    evidence_by_id = {
        row.id: row
        for row in db.scalars(
            select(GeoEvidence).where(GeoEvidence.id.in_(evidence_ids or [-1]))
        )
    }
    invalid_reasons: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    source_domains: Counter[str] = Counter()
    positions: list[int] = []
    by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {"expected": 0, "eligible": 0, "positive": 0}
    )
    weighted_sum = 0
    eligible = 0
    for task in tasks:
        model_key = task.model_key
        by_model[model_key]["expected"] += 1
        evidence = evidence_by_id.get(task.evidence_id or 0)
        reason = _eligibility_reason(task, evidence)
        if reason:
            invalid_reasons[reason] += 1
            continue
        assert evidence is not None
        eligible += 1
        by_model[model_key]["eligible"] += 1
        status = evidence.brand_status
        status_counts[status] += 1
        weighted_sum += STATUS_WEIGHT.get(status, 0)
        if status in POSITIVE_STATUSES:
            by_model[model_key]["positive"] += 1
        if evidence.brand_position is not None:
            positions.append(evidence.brand_position)
        for url in _source_urls(evidence):
            domain = urlsplit(url).hostname
            if domain:
                source_domains[domain.lower()] += 1

    scope = batch_scope(
        batch,
        question_plan_id=question_plan_id,
        question_plan_ids=sorted(selected_question_ids) or None,
        provider_ids=provider_ids,
    )
    expected = int(scope["expected_samples"] or len(tasks))
    positive = sum(status_counts[status] for status in POSITIVE_STATUSES)
    shortlisted = status_counts["shortlisted"] + status_counts["recommended"]
    metrics = {
        "batch_id": batch.id,
        "batch_status": batch.status,
        "expected_samples": expected,
        "task_count": len(tasks),
        "eligible_samples": eligible,
        "ineligible_samples": max(expected - eligible, 0),
        "invalid_reasons": dict(sorted(invalid_reasons.items())),
        "brand_status_counts": dict(sorted(status_counts.items())),
        "positive_count": positive,
        "mention_rate": round(positive / eligible, 4) if eligible else 0.0,
        "shortlist_or_recommend_count": shortlisted,
        "recommend_count": status_counts["recommended"],
        "citation_count": status_counts["cited"],
        "impact_score": round(weighted_sum / (3 * eligible), 4) if eligible else 0.0,
        "average_brand_position": round(sum(positions) / len(positions), 2) if positions else None,
        "source_domains": [domain for domain, _count in source_domains.most_common(20)],
        "by_model": dict(sorted(by_model.items())),
        "evidence_gate": "completed_task+real_answer+search_event+source_url+raw_artifact",
        "scope": scope,
    }
    return metrics


def batch_scope(
    batch: GeoObservationBatch,
    *,
    question_plan_id: int | None = None,
    question_plan_ids: list[int] | None = None,
    provider_ids: list[int] | None = None,
) -> dict:
    configuration = batch.configuration or {}
    provider_filter = set(provider_ids or [])
    providers = sorted(
        (
            int(item.get("id") or 0),
            str(item.get("key") or ""),
            str(item.get("model_name") or ""),
        )
        for item in configuration.get("providers") or []
        if isinstance(item, dict)
        and (not provider_filter or int(item.get("id") or 0) in provider_filter)
    )
    selected_question_ids = set(question_plan_ids or [])
    if question_plan_id is not None:
        selected_question_ids.add(question_plan_id)
    questions = sorted(
        int(item.get("id") or 0)
        for item in configuration.get("questions") or []
        if isinstance(item, dict)
        and (
            not selected_question_ids
            or int(item.get("id") or 0) in selected_question_ids
        )
    )
    return {
        "provider_versions": [
            {"provider_id": provider_id, "model_key": model_key, "model_name": model_name}
            for provider_id, model_key, model_name in providers
        ],
        "question_plan_ids": questions,
        "repeat_count": int(batch.repeat_count or 0),
        "expected_samples": len(providers) * len(questions) * int(batch.repeat_count or 0),
    }


def compare_batches(
    baseline_batch: GeoObservationBatch,
    retest_batch: GeoObservationBatch,
    baseline_metrics: dict,
    retest_metrics: dict,
) -> tuple[str, dict]:
    baseline_scope = baseline_metrics.get("scope") or batch_scope(baseline_batch)
    retest_scope = retest_metrics.get("scope") or batch_scope(retest_batch)
    scope_match = baseline_scope == retest_scope
    baseline_complete = (
        baseline_metrics.get("eligible_samples") == baseline_metrics.get("expected_samples")
        and int(baseline_metrics.get("expected_samples") or 0) > 0
    )
    retest_complete = (
        retest_metrics.get("eligible_samples") == retest_metrics.get("expected_samples")
        and int(retest_metrics.get("expected_samples") or 0) > 0
    )
    comparable = scope_match and baseline_complete and retest_complete
    delta = {
        "comparable": comparable,
        "scope_match": scope_match,
        "baseline_complete": baseline_complete,
        "retest_complete": retest_complete,
        "baseline_scope": baseline_scope,
        "retest_scope": retest_scope,
        "mention_rate": round(
            float(retest_metrics.get("mention_rate") or 0)
            - float(baseline_metrics.get("mention_rate") or 0),
            4,
        ),
        "positive_count": int(retest_metrics.get("positive_count") or 0)
        - int(baseline_metrics.get("positive_count") or 0),
        "recommend_count": int(retest_metrics.get("recommend_count") or 0)
        - int(baseline_metrics.get("recommend_count") or 0),
        "citation_count": int(retest_metrics.get("citation_count") or 0)
        - int(baseline_metrics.get("citation_count") or 0),
        "impact_score": round(
            float(retest_metrics.get("impact_score") or 0)
            - float(baseline_metrics.get("impact_score") or 0),
            4,
        ),
        "interpretation": "观测变化不代表发布行为构成因果，只描述同口径复测差异。",
    }
    if not comparable:
        return "insufficient_evidence", delta
    impact_delta = float(delta["impact_score"])
    if impact_delta > 0:
        return "improved", delta
    if impact_delta < 0:
        return "regressed", delta
    return "unchanged", delta
