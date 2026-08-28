"""Honest action-effect and business ROI calculations over persisted ledgers."""

from __future__ import annotations

from collections import Counter
from math import ceil
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import (
    GeoActionOpportunity,
    GeoBusinessMetricEntry,
    GeoObservationBatch,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoReobservation,
    GeoWorkspace,
)
from app.v1.action_retests import build_batch_metrics


COST_METRICS = {"content_cost", "labor_cost", "distribution_cost", "tool_cost"}
MONEY_METRICS = COST_METRICS | {"pipeline_value", "won_revenue"}
QUANTITY_METRICS = {"ai_referral_visit", "qualified_lead", "sales_opportunity"}
METRIC_LABELS = {
    "content_cost": "内容制作成本",
    "labor_cost": "内部人力成本",
    "distribution_cost": "分发与媒体成本",
    "tool_cost": "模型与工具成本",
    "ai_referral_visit": "AI 引荐访问",
    "qualified_lead": "有效线索",
    "sales_opportunity": "销售商机",
    "pipeline_value": "商机管道金额",
    "won_revenue": "已成交收入",
}


def default_measurement_plan(
    action: GeoOptimizationAction,
    opportunity: GeoActionOpportunity | None,
) -> dict:
    opportunity_type = str(opportunity.opportunity_type if opportunity else "")
    if "citation" in opportunity_type or "website" in opportunity_type:
        primary_metric, label, direction = "citation_count", "引用次数", "higher"
    elif "recommend" in opportunity_type or "comparison" in opportunity_type:
        primary_metric, label, direction = "recommend_count", "推荐次数", "higher"
    elif "rank" in opportunity_type:
        primary_metric, label, direction = "average_brand_position", "平均出现位置", "lower"
    else:
        primary_metric, label, direction = "impact_score", "综合影响分", "higher"
    return {
        "schema": "action-measurement/v1",
        "primary_metric": primary_metric,
        "primary_metric_label": label,
        "direction": direction,
        "minimum_comparable_rounds_for_stability": 2,
        "minimum_model_agreement": 0.5,
        "baseline_batch_id": int((action.baseline_snapshot or {}).get("batch_id") or 0) or None,
        "principle": "同模型、同问题、同重复次数；单轮改善只作为观察信号。",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _model_signal(row: GeoReobservation) -> dict:
    baseline = (row.baseline_metrics or {}).get("by_model") or {}
    retest = (row.retest_metrics or {}).get("by_model") or {}
    directions = []
    for model_key in sorted(set(baseline) & set(retest)):
        before = baseline.get(model_key) or {}
        after = retest.get(model_key) or {}
        before_eligible = int(before.get("eligible") or 0)
        after_eligible = int(after.get("eligible") or 0)
        if before_eligible < 1 or after_eligible < 1:
            continue
        before_rate = float(before.get("positive") or 0) / before_eligible
        after_rate = float(after.get("positive") or 0) / after_eligible
        delta = round(after_rate - before_rate, 4)
        direction = "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged"
        directions.append(
            {
                "model_key": model_key,
                "direction": direction,
                "before_rate": round(before_rate, 4),
                "after_rate": round(after_rate, 4),
                "delta": delta,
            }
        )
    improved = sum(item["direction"] == "improved" for item in directions)
    regressed = sum(item["direction"] == "regressed" for item in directions)
    return {
        "directions": directions,
        "improvement_ratio": round(improved / len(directions), 4) if directions else None,
        "no_regression": bool(directions) and regressed == 0,
    }


def derive_action_outcome(rows: list[GeoReobservation]) -> dict:
    completed = [row for row in rows if row.status == "completed"]
    comparable = [row for row in completed if (row.measured_delta or {}).get("comparable") is True]
    if not rows:
        return {
            "status": "not_measured",
            "label": "尚未复测",
            "confidence": "none",
            "confidence_label": "暂无证据",
            "comparable_rounds": 0,
            "model_agreement": None,
        }
    if not comparable:
        return {
            "status": "insufficient_evidence",
            "label": "证据不足",
            "confidence": "none",
            "confidence_label": "不可比较",
            "comparable_rounds": 0,
            "model_agreement": None,
        }
    latest = comparable[-1]
    latest_signal = _model_signal(latest)
    last_two = comparable[-2:]
    stable = len(last_two) == 2 and all(
        row.conclusion == "improved"
        and (signal := _model_signal(row))["no_regression"]
        and float(signal["improvement_ratio"] or 0) >= 0.5
        for row in last_two
    )
    if stable:
        status, label = "stable_improvement", "稳定改善"
    elif latest.conclusion == "improved":
        status, label = "observed_improvement", "观察到改善"
    elif latest.conclusion == "regressed":
        status, label = "regressed", "出现回退"
    else:
        status, label = "no_clear_change", "暂无明显变化"
    confidence = "high" if stable and len(comparable) >= 3 else "medium" if stable else "low"
    confidence_label = {"high": "较高", "medium": "中等", "low": "初步"}[confidence]
    return {
        "status": status,
        "label": label,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "comparable_rounds": len(comparable),
        "model_agreement": latest_signal["improvement_ratio"],
        "latest_model_directions": latest_signal["directions"],
        "causal_warning": "这里只证明同口径结果发生变化，不自动证明变化完全由该行动造成。",
    }


def _metric_value(metrics: dict, key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _action_result(
    action: GeoOptimizationAction,
    opportunity: GeoActionOpportunity | None,
    question: GeoQuestionPlan | None,
    rows: list[GeoReobservation],
) -> dict:
    plan = action.measurement_plan or default_measurement_plan(action, opportunity)
    primary = str(plan.get("primary_metric") or "impact_score")
    outcome = derive_action_outcome(rows)
    points = []
    completed = [row for row in rows if row.status == "completed"]
    first_with_baseline = next((row for row in completed if row.baseline_metrics), None)
    if first_with_baseline:
        points.append(
            {
                "kind": "baseline",
                "label": "优化前",
                "round_index": 0,
                "batch_id": first_with_baseline.baseline_batch_id,
                "value": _metric_value(first_with_baseline.baseline_metrics or {}, primary),
                "captured_at": first_with_baseline.started_at,
            }
        )
    for row in completed:
        points.append(
            {
                "kind": "retest",
                "label": f"第 {row.round_index} 轮复测",
                "round_index": row.round_index,
                "batch_id": row.retest_batch_id,
                "value": _metric_value(row.retest_metrics or {}, primary),
                "captured_at": row.completed_at,
                "conclusion": row.conclusion,
                "comparable": bool((row.measured_delta or {}).get("comparable")),
            }
        )
    latest = completed[-1] if completed else None
    return {
        "action_id": action.id,
        "title": action.title,
        "status": action.status,
        "stage": action.stage,
        "question": question.question_text if question else None,
        "opportunity_type": opportunity.opportunity_type if opportunity else None,
        "measurement_plan": plan,
        "outcome": outcome,
        "round_count": len(rows),
        "latest_retest_id": latest.id if latest else None,
        "latest_completed_at": latest.completed_at if latest else None,
        "latest_delta": (latest.measured_delta or {}) if latest else {},
        "trend": points,
    }


def _historical_model_directions(first_metrics: dict, latest_metrics: dict) -> list[dict]:
    directions = []
    first_models = first_metrics.get("by_model") or {}
    latest_models = latest_metrics.get("by_model") or {}
    for model_key in sorted(set(first_models) & set(latest_models)):
        before = first_models[model_key]
        after = latest_models[model_key]
        before_total = int(before.get("eligible") or 0)
        after_total = int(after.get("eligible") or 0)
        if before_total < 1 or after_total < 1:
            continue
        before_rate = float(before.get("positive") or 0) / before_total
        after_rate = float(after.get("positive") or 0) / after_total
        delta = round((after_rate - before_rate) * 100, 1)
        directions.append(
            {
                "model_key": model_key,
                "before_positive": int(before.get("positive") or 0),
                "before_total": before_total,
                "after_positive": int(after.get("positive") or 0),
                "after_total": after_total,
                "delta_percentage_points": delta,
                "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
            }
        )
    return directions


def build_historical_observations(
    db: Session,
    workspace_id: int,
    actions: list[GeoOptimizationAction],
    *,
    period_days: int = 30,
    model_key: str | None = None,
    model_keys: list[str] | None = None,
    question_plan_id: int | None = None,
    question_plan_ids: list[int] | None = None,
    batch_ids: list[int] | None = None,
) -> dict:
    """Build a preview from old real batches without claiming action attribution."""
    selected_question_ids = set(question_plan_ids or [])
    if question_plan_id is not None:
        selected_question_ids.add(question_plan_id)
    selected_model_keys = set(model_keys or [])
    if model_key:
        selected_model_keys.add(model_key)
    selected_batch_ids = set(batch_ids or [])
    all_batches = list(
        db.scalars(
            select(GeoObservationBatch)
            .where(
                GeoObservationBatch.workspace_id == workspace_id,
                GeoObservationBatch.status == "completed",
                GeoObservationBatch.source_type.in_(
                    ["official_api", "official_api_single", "action_retest"]
                ),
            )
            .order_by(GeoObservationBatch.completed_at, GeoObservationBatch.id)
        )
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    batches = [
        batch
        for batch in all_batches
        if (not selected_batch_ids or batch.id in selected_batch_ids)
        if (batch.completed_at or batch.created_at).replace(tzinfo=timezone.utc)
        >= cutoff
    ][-16:]
    model_options: dict[str, str] = {}
    for batch in all_batches:
        for provider in (batch.configuration or {}).get("providers") or []:
            if not isinstance(provider, dict):
                continue
            key = str(provider.get("model_key") or provider.get("key") or "").strip()
            if key:
                model_options[key] = str(provider.get("label") or key)
    question_rows = list(
        db.scalars(
            select(GeoQuestionPlan)
            .where(GeoQuestionPlan.workspace_id == workspace_id)
            .order_by(GeoQuestionPlan.id)
        )
    )
    series = []
    for batch in batches:
        configured_providers = [
            item
            for item in (batch.configuration or {}).get("providers") or []
            if isinstance(item, dict)
            and (
                not selected_model_keys
                or str(item.get("model_key") or item.get("key") or "") in selected_model_keys
            )
        ]
        provider_ids = [
            int(item.get("id") or 0)
            for item in configured_providers
            if int(item.get("id") or 0) > 0
        ]
        if selected_model_keys and not provider_ids:
            continue
        configured_questions = {
            int(item.get("id") or 0)
            for item in (batch.configuration or {}).get("questions") or []
            if isinstance(item, dict)
        }
        if selected_question_ids and not selected_question_ids.intersection(configured_questions):
            continue
        metrics = build_batch_metrics(
            db,
            batch,
            question_plan_ids=sorted(selected_question_ids) or None,
            provider_ids=provider_ids if selected_model_keys else None,
        )
        if int(metrics.get("eligible_samples") or 0) < 1:
            continue
        eligible = int(metrics.get("eligible_samples") or 0)
        high_value = int(metrics.get("recommend_count") or 0) + int(
            metrics.get("citation_count") or 0
        )
        series.append(
            {
                "batch_id": batch.id,
                "captured_at": batch.completed_at or batch.created_at,
                "mention_rate": round(float(metrics.get("mention_rate") or 0) * 100, 1),
                "impact_score": round(float(metrics.get("impact_score") or 0) * 100, 1),
                "shortlist_rate": round(
                    int(metrics.get("shortlist_or_recommend_count") or 0) / eligible * 100,
                    1,
                ),
                "high_value_rate": round(high_value / eligible * 100, 1),
                "eligible_samples": eligible,
                "expected_samples": int(metrics.get("expected_samples") or 0),
                "complete": eligible == int(metrics.get("expected_samples") or 0),
            }
        )
    question_cache: dict[int, list[tuple[GeoObservationBatch, dict]]] = {}
    for question_id in sorted({action.question_plan_id for action in actions if action.question_plan_id}):
        observations = []
        for batch in batches:
            configured_questions = {
                int(item.get("id") or 0)
                for item in (batch.configuration or {}).get("questions") or []
                if isinstance(item, dict)
            }
            if question_id not in configured_questions:
                continue
            configured_providers = [
                item
                for item in (batch.configuration or {}).get("providers") or []
                if isinstance(item, dict)
                and (
                    not selected_model_keys
                    or str(item.get("model_key") or item.get("key") or "") in selected_model_keys
                )
            ]
            provider_ids = [
                int(item.get("id") or 0)
                for item in configured_providers
                if int(item.get("id") or 0) > 0
            ]
            if selected_model_keys and not provider_ids:
                continue
            metrics = build_batch_metrics(
                db,
                batch,
                question_plan_id=question_id,
                provider_ids=provider_ids if selected_model_keys else None,
            )
            if (
                int(metrics.get("eligible_samples") or 0) > 0
                and metrics.get("eligible_samples") == metrics.get("expected_samples")
            ):
                observations.append((batch, metrics))
        question_cache[question_id] = observations
    action_signals = {}
    signal_counts: Counter[str] = Counter()
    for action in actions:
        observations = question_cache.get(action.question_plan_id or 0, [])
        if not observations:
            signal = {
                "status": "no_history",
                "label": "暂无历史观测",
                "scope_quality": "none",
                "scope_label": "暂无参考",
                "observation_count": 0,
                "attribution": "not_attributed",
            }
        else:
            first_batch, first_metrics = observations[0]
            latest_batch, latest_metrics = observations[-1]
            before_positive = int(first_metrics.get("positive_count") or 0)
            before_total = int(first_metrics.get("eligible_samples") or 0)
            after_positive = int(latest_metrics.get("positive_count") or 0)
            after_total = int(latest_metrics.get("eligible_samples") or 0)
            before_rate = before_positive / before_total if before_total else 0
            after_rate = after_positive / after_total if after_total else 0
            delta = round((after_rate - before_rate) * 100, 1)
            same_scope = (first_metrics.get("scope") or {}) == (latest_metrics.get("scope") or {})
            status = "history_up" if delta > 0 else "history_down" if delta < 0 else "history_flat"
            label = "历史上升" if delta > 0 else "历史回落" if delta < 0 else "历史持平"
            signal = {
                "status": status,
                "label": label,
                "scope_quality": "same_scope" if same_scope else "mixed_scope",
                "scope_label": "同口径参考" if same_scope else "跨批次参考",
                "observation_count": len(observations),
                "before_positive": before_positive,
                "before_total": before_total,
                "after_positive": after_positive,
                "after_total": after_total,
                "delta_percentage_points": delta,
                "first_batch_id": first_batch.id,
                "latest_batch_id": latest_batch.id,
                "first_captured_at": first_batch.completed_at or first_batch.created_at,
                "latest_captured_at": latest_batch.completed_at or latest_batch.created_at,
                "model_directions": _historical_model_directions(first_metrics, latest_metrics),
                "attribution": "not_attributed",
                "warning": "这是真实历史观测变化，不代表该行动已经产生效果。",
            }
        action_signals[action.id] = signal
        signal_counts[signal["status"]] += 1
    if len(series) >= 2:
        change = round(series[-1]["mention_rate"] - series[0]["mention_rate"], 1)
    else:
        change = None
    complete_batches = sum(point["complete"] for point in series)
    return {
        "mode": "historical_preview",
        "label": "历史观测参考",
        "warning": "历史批次的模型、问题或重复次数可能不同，只用于丰富首屏，不作为行动归因结论。",
        "series": series,
        "change_percentage_points": change,
        "complete_batch_count": complete_batches,
        "batch_count": len(series),
        "signal_counts": dict(sorted(signal_counts.items())),
        "filters": {
            "period_days": period_days,
            "model_key": model_key,
            "question_plan_id": question_plan_id,
            "question_plan_ids": sorted(selected_question_ids),
            **(
                {"model_keys": sorted(selected_model_keys)}
                if selected_model_keys and (len(selected_model_keys) > 1 or model_key is None)
                else {}
            ),
            **({"batch_ids": sorted(selected_batch_ids)} if selected_batch_ids else {}),
        },
        "model_options": [
            {"key": key, "label": label} for key, label in sorted(model_options.items())
        ],
        "question_options": [
            {"id": row.id, "label": row.question_text} for row in question_rows
        ],
        "action_signals": action_signals,
    }


def build_effect_overview(
    db: Session,
    workspace_id: int,
    *,
    period_days: int = 30,
    model_key: str | None = None,
    model_keys: list[str] | None = None,
    question_plan_id: int | None = None,
    question_plan_ids: list[int] | None = None,
    batch_ids: list[int] | None = None,
) -> dict:
    selected_question_ids = set(question_plan_ids or [])
    if question_plan_id is not None:
        selected_question_ids.add(question_plan_id)
    actions = list(
        db.scalars(
            select(GeoOptimizationAction)
            .where(
                GeoOptimizationAction.workspace_id == workspace_id,
                *(
                    [GeoOptimizationAction.question_plan_id.in_(selected_question_ids)]
                    if selected_question_ids
                    else []
                ),
            )
            .order_by(GeoOptimizationAction.id.desc())
        )
    )
    action_ids = [action.id for action in actions]
    rows = list(
        db.scalars(
            select(GeoReobservation)
            .where(GeoReobservation.workspace_id == workspace_id)
            .order_by(GeoReobservation.action_id, GeoReobservation.round_index)
        )
    )
    rows_by_action: dict[int, list[GeoReobservation]] = {action_id: [] for action_id in action_ids}
    for row in rows:
        rows_by_action.setdefault(row.action_id, []).append(row)
    opportunity_ids = [action.opportunity_id for action in actions if action.opportunity_id]
    question_ids = [action.question_plan_id for action in actions if action.question_plan_id]
    opportunities = {
        row.id: row
        for row in db.scalars(
            select(GeoActionOpportunity).where(GeoActionOpportunity.id.in_(opportunity_ids or [-1]))
        )
    }
    questions = {
        row.id: row
        for row in db.scalars(
            select(GeoQuestionPlan).where(GeoQuestionPlan.id.in_(question_ids or [-1]))
        )
    }
    items = [
        _action_result(
            action,
            opportunities.get(action.opportunity_id or 0),
            questions.get(action.question_plan_id or 0),
            rows_by_action.get(action.id, []),
        )
        for action in actions
    ]
    counts = Counter(item["outcome"]["status"] for item in items)
    historical = build_historical_observations(
        db,
        workspace_id,
        actions,
        period_days=period_days,
        model_key=model_key,
        model_keys=model_keys,
        question_plan_id=question_plan_id,
        question_plan_ids=sorted(selected_question_ids),
        batch_ids=batch_ids,
    )
    for item in items:
        item["historical_signal"] = historical["action_signals"].get(item["action_id"])
    measured = sum(item["outcome"]["status"] != "not_measured" for item in items)
    if counts["stable_improvement"]:
        headline = f"{counts['stable_improvement']} 个行动已形成稳定改善证据"
    elif counts["observed_improvement"]:
        headline = f"{counts['observed_improvement']} 个行动观察到改善，仍需下一轮验证"
    elif measured:
        headline = "已有复测结果，但暂未形成稳定改善证据"
    else:
        headline = "还没有可比较的行动复测"
    return {
        "headline": headline,
        "description": "结果只来自真实观测批次；单轮变化不作稳定结论。",
        "total_actions": len(actions),
        "measured_actions": measured,
        "counts": dict(sorted(counts.items())),
        "actions": items,
        "historical": {
            key: value for key, value in historical.items() if key != "action_signals"
        },
    }


def _entry_read(entry: GeoBusinessMetricEntry) -> dict:
    return {
        "id": entry.id,
        "action_id": entry.action_id,
        "metric_type": entry.metric_type,
        "metric_label": METRIC_LABELS.get(entry.metric_type, entry.metric_type),
        "amount_minor": entry.amount_minor,
        "quantity": entry.quantity,
        "currency": entry.currency,
        "attribution_type": entry.attribution_type,
        "source_type": entry.source_type,
        "source_label": entry.source_label,
        "source_reference": entry.source_reference,
        "evidence_note": entry.evidence_note,
        "verification_status": entry.verification_status,
        "occurred_at": entry.occurred_at,
        "created_by_user_id": entry.created_by_user_id,
        "reverses_entry_id": entry.reverses_entry_id,
        "reversal_reason": entry.reversal_reason,
        "is_reversal": entry.reverses_entry_id is not None,
        "created_at": entry.created_at,
    }


def build_roi_overview(
    db: Session,
    workspace_id: int,
    *,
    period_days: int = 30,
    action_ids: list[int] | None = None,
    action_results: list[dict] | None = None,
) -> dict:
    selected_action_ids = sorted(set(action_ids or []))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=period_days)
    previous_cutoff = cutoff - timedelta(days=period_days)
    entry_query = select(GeoBusinessMetricEntry).where(
        GeoBusinessMetricEntry.workspace_id == workspace_id,
        GeoBusinessMetricEntry.occurred_at >= cutoff,
    )
    if selected_action_ids:
        entry_query = entry_query.where(GeoBusinessMetricEntry.action_id.in_(selected_action_ids))
    entries = list(
        db.scalars(
            entry_query.order_by(
                GeoBusinessMetricEntry.occurred_at.desc(), GeoBusinessMetricEntry.id.desc()
            )
        )
    )
    previous_query = select(GeoBusinessMetricEntry).where(
        GeoBusinessMetricEntry.workspace_id == workspace_id,
        GeoBusinessMetricEntry.occurred_at >= previous_cutoff,
        GeoBusinessMetricEntry.occurred_at < cutoff,
    )
    if selected_action_ids:
        previous_query = previous_query.where(
            GeoBusinessMetricEntry.action_id.in_(selected_action_ids)
        )
    previous_entries = list(db.scalars(previous_query))
    confirmed = [entry for entry in entries if entry.verification_status in {"user_confirmed", "system_verified"}]
    previous_confirmed = [
        entry
        for entry in previous_entries
        if entry.verification_status in {"user_confirmed", "system_verified"}
    ]
    monetary = [entry for entry in confirmed if entry.metric_type in MONEY_METRICS]
    roi_monetary = [
        entry
        for entry in monetary
        if entry.metric_type in COST_METRICS or entry.metric_type == "won_revenue"
    ]
    currencies = sorted({entry.currency for entry in roi_monetary if entry.currency})
    cost = sum(int(entry.amount_minor or 0) for entry in confirmed if entry.metric_type in COST_METRICS)
    attributable_revenue_sources = [
        entry
        for entry in confirmed
        if entry.metric_type == "won_revenue"
        and entry.attribution_type == "direct"
        and entry.action_id is not None
        and entry.source_type in {"crm", "finance"}
        and bool(entry.source_reference)
    ]
    attributable_source_ids = {entry.id for entry in attributable_revenue_sources}
    attributable_revenue_entries = attributable_revenue_sources + [
        entry
        for entry in confirmed
        if entry.reverses_entry_id in attributable_source_ids
    ]
    direct_revenue = sum(
        int(entry.amount_minor or 0)
        for entry in attributable_revenue_entries
    )

    def period_totals(period_entries: list[GeoBusinessMetricEntry]) -> dict:
        period_cost = sum(
            int(entry.amount_minor or 0)
            for entry in period_entries
            if entry.metric_type in COST_METRICS
        )
        valid_sources = [
            entry
            for entry in period_entries
            if entry.metric_type == "won_revenue"
            and entry.attribution_type == "direct"
            and entry.action_id is not None
            and entry.source_type in {"crm", "finance"}
            and bool(entry.source_reference)
        ]
        valid_ids = {entry.id for entry in valid_sources}
        period_revenue = sum(
            int(entry.amount_minor or 0)
            for entry in period_entries
            if entry in valid_sources or entry.reverses_entry_id in valid_ids
        )
        period_currencies = {
            entry.currency
            for entry in period_entries
            if entry.metric_type in COST_METRICS | {"won_revenue"} and entry.currency
        }
        period_roi = (
            round((period_revenue - period_cost) / period_cost * 100, 2)
            if period_cost > 0 and len(period_currencies) == 1
            else None
        )
        return {
            "cost_minor": period_cost,
            "revenue_minor": period_revenue,
            "net_value_minor": period_revenue - period_cost if period_cost > 0 else None,
            "roi_percent": period_roi,
        }

    previous_totals = period_totals(previous_confirmed)
    assisted_revenue = sum(
        int(entry.amount_minor or 0)
        for entry in monetary
        if entry.metric_type == "won_revenue" and entry.attribution_type == "assisted"
    )
    pipeline_value = sum(
        int(entry.amount_minor or 0)
        for entry in monetary
        if entry.metric_type == "pipeline_value" and entry.attribution_type in {"direct", "assisted"}
    )
    quantities = {
        metric: round(
            sum(float(entry.quantity or 0) for entry in confirmed if entry.metric_type == metric), 2
        )
        for metric in sorted(QUANTITY_METRICS)
    }
    missing = []
    if not any(entry.metric_type in COST_METRICS for entry in confirmed):
        missing.append("尚未记录已确认成本")
    elif cost <= 0:
        missing.append("已确认成本必须大于 0")
    direct_revenue_records = [
        entry
        for entry in confirmed
        if entry.metric_type == "won_revenue" and entry.attribution_type == "direct"
    ]
    if not attributable_revenue_entries:
        if direct_revenue_records:
            missing.append("已记录直接成交，但缺少关联行动或 CRM/财务凭证编号")
        else:
            missing.append("尚未记录有行动和凭证支持的直接成交收入")
    if len(currencies) > 1:
        missing.append("存在多种币种，需先统一币种后计算")
    if monetary and any(not entry.currency for entry in monetary):
        missing.append("存在未填写币种的金额记录")
    calculable = not missing and len(currencies) == 1
    roi_percent = round((direct_revenue - cost) / cost * 100, 2) if calculable else None
    action_rows = list(
        db.scalars(
            select(GeoOptimizationAction)
            .where(GeoOptimizationAction.workspace_id == workspace_id)
            .order_by(GeoOptimizationAction.id.desc())
        )
    )
    effect_by_action = {
        int(item["action_id"]): item for item in (action_results or []) if item.get("action_id")
    }
    scoped_actions = [
        row for row in action_rows if not selected_action_ids or row.id in selected_action_ids
    ]
    action_portfolio = []
    for action in scoped_actions:
        action_entries = [entry for entry in confirmed if entry.action_id == action.id]
        action_cost = sum(
            int(entry.amount_minor or 0)
            for entry in action_entries
            if entry.metric_type in COST_METRICS
        )
        action_revenue = sum(
            int(entry.amount_minor or 0)
            for entry in action_entries
            if entry in attributable_revenue_entries
        )
        action_pipeline = sum(
            int(entry.amount_minor or 0)
            for entry in action_entries
            if entry.metric_type == "pipeline_value"
            and entry.attribution_type in {"direct", "assisted"}
        )
        action_quantities = {
            metric: round(
                sum(
                    float(entry.quantity or 0)
                    for entry in action_entries
                    if entry.metric_type == metric
                ),
                2,
            )
            for metric in sorted(QUANTITY_METRICS)
        }
        effect = effect_by_action.get(action.id) or {}
        outcome = effect.get("outcome") or {}
        comparable_rounds = int(outcome.get("comparable_rounds") or 0)
        if action_revenue > 0:
            recommendation = "进入经营评审"
        elif action_quantities.get("sales_opportunity", 0) > 0:
            recommendation = "跟进商机转化"
        elif action_quantities.get("qualified_lead", 0) > 0:
            recommendation = "跟进线索进商机"
        elif action_quantities.get("ai_referral_visit", 0) > 0:
            recommendation = "补接线索回传"
        elif comparable_rounds > 0:
            recommendation = "补接访问与线索"
        elif action_cost > 0:
            recommendation = "先完成同口径复测"
        else:
            recommendation = "补齐行动投入"
        action_portfolio.append(
            {
                "action_id": action.id,
                "title": action.title,
                "stage": action.stage,
                "effect_status": outcome.get("status") or "not_measured",
                "effect_label": outcome.get("label") or "尚未复测",
                "comparable_rounds": comparable_rounds,
                "cost_minor": action_cost,
                "direct_revenue_minor": action_revenue,
                "pipeline_value_minor": action_pipeline,
                "net_value_minor": action_revenue - action_cost if action_cost > 0 else None,
                "roi_percent": round((action_revenue - action_cost) / action_cost * 100, 2)
                if action_cost > 0
                else None,
                "quantities": action_quantities,
                "recommendation": recommendation,
            }
        )

    effect_ready = any(item["comparable_rounds"] > 0 for item in action_portfolio)
    cost_ready = cost > 0
    referral_ready = quantities.get("ai_referral_visit", 0) > 0
    conversion_ready = any(
        quantities.get(metric, 0) > 0 for metric in ("qualified_lead", "sales_opportunity")
    ) or pipeline_value > 0
    revenue_ready = direct_revenue > 0
    readiness = [
        {
            "key": "cost",
            "label": "投入口径",
            "status": "complete" if cost_ready else "missing",
            "evidence": "已有可追溯成本" if cost_ready else "尚未记录本期成本",
            "next_action": "录入内容、人力、分发或工具成本",
        },
        {
            "key": "effect",
            "label": "GEO 效果",
            "status": "complete" if effect_ready else "missing",
            "evidence": "已有同口径复测" if effect_ready else "尚未形成可比复测",
            "next_action": "为已发布行动创建同问题、同模型复测",
        },
        {
            "key": "traffic",
            "label": "AI 引荐访问",
            "status": "complete" if referral_ready else "missing",
            "evidence": "已有分析平台访问记录" if referral_ready else "尚未接入 AI 引荐访问",
            "next_action": "从分析平台记录 AI 引荐会话",
        },
        {
            "key": "conversion",
            "label": "线索与商机",
            "status": "complete" if conversion_ready else "missing",
            "evidence": "已有 CRM 转化记录" if conversion_ready else "尚未回传有效线索或商机",
            "next_action": "把引荐访问与 CRM 线索/商机关联",
        },
        {
            "key": "revenue",
            "label": "成交回款",
            "status": "complete" if revenue_ready else "missing",
            "evidence": "已有行动与凭证支持的成交" if revenue_ready else "尚未形成可直接归因成交",
            "next_action": "从 CRM/财务表回传成交金额和凭证编号",
        },
    ]
    ready_count = sum(item["status"] == "complete" for item in readiness)
    if calculable and effect_ready:
        decision = {
            "status": "ready_for_review",
            "headline": "已具备投入决策评审条件",
            "summary": "财务回报可计算，且已有同口径 GEO 复测；请结合样本量决定继续、调整或暂停投入。",
        }
    elif calculable:
        decision = {
            "status": "financial_only",
            "headline": "财务回报可算，但 GEO 贡献还没证明",
            "summary": "成本和成交已齐，还需同口径复测证明优化确实改变了模型结果。",
        }
    elif ready_count >= 2:
        decision = {
            "status": "building_evidence",
            "headline": "正在建立从 GEO 到业务结果的证据链",
            "summary": "已有部分记录，但还不足以支持继续投入或暂停的经营决策。",
        }
    else:
        decision = {
            "status": "setup_required",
            "headline": "先建立归因链路，再谈 ROI",
            "summary": "当前不缺一个公式，而是缺少投入、GEO 复测和业务转化之间的可追溯关系。",
        }
    next_missing = next((item for item in readiness if item["status"] == "missing"), None)
    funnel = [
        {"key": "cost", "label": "已确认投入", "value": cost, "kind": "money", "available": cost_ready},
        {
            "key": "effect",
            "label": "有可比复测的行动",
            "value": sum(item["comparable_rounds"] > 0 for item in action_portfolio),
            "kind": "quantity",
            "available": effect_ready,
        },
        {"key": "traffic", "label": "AI 引荐访问", "value": quantities.get("ai_referral_visit", 0), "kind": "quantity", "available": referral_ready},
        {"key": "lead", "label": "有效线索", "value": quantities.get("qualified_lead", 0), "kind": "quantity", "available": quantities.get("qualified_lead", 0) > 0},
        {"key": "opportunity", "label": "销售商机", "value": quantities.get("sales_opportunity", 0), "kind": "quantity", "available": quantities.get("sales_opportunity", 0) > 0},
        {"key": "revenue", "label": "直接成交收入", "value": direct_revenue, "kind": "money", "available": revenue_ready},
    ]

    def percentage_change(current: int, previous: int) -> float | None:
        if previous == 0:
            return None
        return round((current - previous) / abs(previous) * 100, 2)

    current_totals = {
        "cost_minor": cost,
        "revenue_minor": direct_revenue,
        "net_value_minor": direct_revenue - cost if calculable else None,
        "roi_percent": roi_percent,
    }
    comparison = {
        "cost_change_percent": percentage_change(cost, previous_totals["cost_minor"]),
        "revenue_change_percent": percentage_change(
            direct_revenue, previous_totals["revenue_minor"]
        ),
        "net_change_percent": percentage_change(
            current_totals["net_value_minor"] or 0,
            previous_totals["net_value_minor"] or 0,
        )
        if current_totals["net_value_minor"] is not None
        and previous_totals["net_value_minor"] is not None
        else None,
        "roi_change_percentage_points": round(
            float(roi_percent) - float(previous_totals["roi_percent"]), 2
        )
        if roi_percent is not None and previous_totals["roi_percent"] is not None
        else None,
        "previous": previous_totals,
    }

    bucket_days = max(1, ceil(period_days / 24))
    trend = []

    def occurred_utc(entry: GeoBusinessMetricEntry) -> datetime:
        value = entry.occurred_at
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    cursor = cutoff
    while cursor < now:
        bucket_end = min(cursor + timedelta(days=bucket_days), now)
        accumulated = [entry for entry in confirmed if occurred_utc(entry) < bucket_end]
        totals = period_totals(accumulated)
        trend.append(
            {
                "date": bucket_end.isoformat(),
                "cost_minor": totals["cost_minor"],
                "revenue_minor": totals["revenue_minor"],
                "net_value_minor": totals["net_value_minor"],
                "roi_percent": totals["roi_percent"],
            }
        )
        cursor = bucket_end
    if len(trend) == 1:
        trend.insert(
            0,
            {
                "date": cutoff.isoformat(),
                "cost_minor": 0,
                "revenue_minor": 0,
                "net_value_minor": None,
                "roi_percent": None,
            },
        )
    action_markers = []
    for action in scoped_actions:
        action_entries = [entry for entry in confirmed if entry.action_id == action.id]
        if action_entries:
            action_markers.append(
                {
                    "action_id": action.id,
                    "title": action.title,
                    "date": min(occurred_utc(entry) for entry in action_entries).isoformat(),
                }
            )
    return {
        "status": "calculable" if calculable else "tracking" if ready_count else "setup_required",
        "status_label": "可评审" if calculable else "建立中" if ready_count else "待建立",
        "currency": currencies[0] if len(currencies) == 1 else None,
        "total_cost_minor": cost,
        "direct_revenue_minor": direct_revenue,
        "assisted_revenue_minor": assisted_revenue,
        "pipeline_value_minor": pipeline_value,
        "net_value_minor": direct_revenue - cost if calculable else None,
        "roi_percent": roi_percent,
        "quantities": quantities,
        "missing_inputs": missing,
        "formula": "(可直接归因的已成交收入 - 已确认总成本) / 已确认总成本",
        "attribution_note": "辅助归因收入单独展示，不默认计入 ROI。",
        "comparison": comparison,
        "trend": trend,
        "action_markers": sorted(action_markers, key=lambda item: item["date"]),
        "updated_at": entries[0].occurred_at if entries else None,
        "scope": {
            "period_days": period_days,
            "action_ids": selected_action_ids,
            "action_label": scoped_actions[0].title if len(scoped_actions) == 1 else "全部行动",
        },
        "decision": {
            **decision,
            "next_action": next_missing["next_action"] if next_missing else "进入经营评审",
        },
        "readiness": {
            "ready_count": ready_count,
            "total_count": len(readiness),
            "percent": round(ready_count / len(readiness) * 100),
            "items": readiness,
        },
        "funnel": funnel,
        "efficiency": {
            "cost_per_referral_visit_minor": round(cost / quantities["ai_referral_visit"])
            if cost > 0 and quantities["ai_referral_visit"] > 0
            else None,
            "cost_per_qualified_lead_minor": round(cost / quantities["qualified_lead"])
            if cost > 0 and quantities["qualified_lead"] > 0
            else None,
            "pipeline_to_cost_multiple": round(pipeline_value / cost, 2)
            if cost > 0 and pipeline_value > 0
            else None,
            "direct_revenue_to_cost_multiple": round(direct_revenue / cost, 2)
            if cost > 0 and direct_revenue > 0
            else None,
        },
        "action_options": [{"id": row.id, "label": row.title} for row in action_rows],
        "action_portfolio": action_portfolio,
        "unallocated_entry_count": sum(entry.action_id is None for entry in confirmed),
        "guardrails": [
            "只有关联具体行动并带 CRM/财务凭证的直接成交计入 ROI。",
            "商机金额和辅助收入只用于观察贡献，不当作已实现收入。",
            "GEO 效果必须来自同问题、同模型、同重复次数的可比复测。",
        ],
        "entry_count": len(entries),
        "entries": [_entry_read(entry) for entry in entries[:100]],
    }


def build_results_overview(
    db: Session,
    workspace: GeoWorkspace,
    *,
    period_days: int = 30,
    model_key: str | None = None,
    model_keys: list[str] | None = None,
    question_plan_id: int | None = None,
    question_plan_ids: list[int] | None = None,
    batch_ids: list[int] | None = None,
    roi_action_ids: list[int] | None = None,
) -> dict:
    effect = build_effect_overview(
        db,
        workspace.id,
        period_days=period_days,
        model_key=model_key,
        model_keys=model_keys,
        question_plan_id=question_plan_id,
        question_plan_ids=question_plan_ids,
        batch_ids=batch_ids,
    )
    return {
        "workspace": {"id": workspace.id, "brand_name": workspace.brand_name},
        "generated_at": datetime.now(timezone.utc),
        "effect": effect,
        "roi": build_roi_overview(
            db,
            workspace.id,
            period_days=period_days,
            action_ids=roi_action_ids,
            action_results=effect["actions"],
        ),
    }
