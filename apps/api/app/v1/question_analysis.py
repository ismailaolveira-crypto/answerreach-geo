"""Deterministic, question-scoped analysis over archived real evidence.

This module deliberately does not call a model.  A question detail page must
explain numbers from the evidence already stored for that exact question.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Iterable

from app.models.cleanroom_v1 import GeoEvidence, GeoQuestionPlan, GeoWorkspace
from app.v1.competitor_comparison import build_competitor_comparison
from app.v1.source_map import normalize_source_url


MENTIONED_STATUSES = {"mentioned", "shortlisted", "recommended", "cited", "negative"}
CANDIDATE_STATUSES = {"shortlisted", "recommended"}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _metric(rows: list[GeoEvidence]) -> dict:
    total = len(rows)
    mentioned = sum(row.brand_status in MENTIONED_STATUSES for row in rows)
    candidates = sum(row.brand_status in CANDIDATE_STATUSES for row in rows)
    recommended = sum(row.brand_status == "recommended" for row in rows)
    cited = sum(row.brand_status == "cited" for row in rows)
    source_answers = sum(bool(row.source_items) for row in rows)
    positions = [row.brand_position for row in rows if row.brand_position is not None]
    return {
        "answer_count": total,
        "mention_count": mentioned,
        "mention_rate": round(mentioned / total * 100, 1) if total else 0.0,
        "candidate_count": candidates,
        "recommendation_count": recommended,
        "recommendation_rate": round(recommended / total * 100, 1) if total else 0.0,
        "cited_count": cited,
        "brand_citation_rate": round(cited / total * 100, 1) if total else 0.0,
        "answers_with_sources": source_answers,
        "source_rate": round(source_answers / total * 100, 1) if total else 0.0,
        "average_position": round(mean(positions), 2) if positions else None,
        "position_observation_count": len(positions),
    }


def _delta(current: dict, previous: dict) -> dict:
    fields = ("mention_rate", "candidate_count", "recommendation_count", "source_rate", "average_position")
    result: dict[str, float | int | None] = {}
    if not previous.get("answer_count"):
        return {**{field: None for field in fields}, "answer_count": None}
    for field in fields:
        current_value = current.get(field)
        previous_value = previous.get(field)
        if current_value is None or previous_value is None:
            result[field] = None
        else:
            result[field] = round(current_value - previous_value, 2)
    result["answer_count"] = current.get("answer_count", 0) - previous.get("answer_count", 0)
    return result


def _source_stats(rows: Iterable[GeoEvidence], limit: int = 12) -> list[dict]:
    aggregates: dict[str, dict] = {}
    for evidence in rows:
        seen: set[str] = set()
        for source in evidence.source_items or []:
            if not isinstance(source, dict):
                continue
            normalized = normalize_source_url(source.get("url"))
            if normalized is None or normalized.page_key in seen:
                continue
            seen.add(normalized.page_key)
            item = aggregates.setdefault(
                normalized.page_key,
                {
                    "key": normalized.page_key,
                    "domain": normalized.domain,
                    "url": normalized.canonical_url,
                    "title": (source.get("title") or "").strip() or normalized.domain,
                    "appearance_count": 0,
                    "evidence_ids": set(),
                    "models": defaultdict(lambda: {"label": evidence.model_label, "count": 0}),
                },
            )
            item["appearance_count"] += 1
            item["evidence_ids"].add(evidence.id)
            model = item["models"][evidence.model_key]
            model["label"] = evidence.model_label
            model["count"] += 1
    rows_out: list[dict] = []
    for item in aggregates.values():
        favored = [
            {"key": key, "label": value["label"], "count": value["count"]}
            for key, value in item["models"].items()
        ]
        favored.sort(key=lambda value: (-value["count"], value["label"]))
        rows_out.append(
            {
                "key": item["key"],
                "domain": item["domain"],
                "url": item["url"],
                "title": item["title"],
                "appearance_count": item["appearance_count"],
                "model_count": len(item["models"]),
                "favored_models": favored,
                "evidence_ids": sorted(item["evidence_ids"], reverse=True),
            }
        )
    rows_out.sort(key=lambda value: (-value["appearance_count"], value["domain"], value["title"]))
    return rows_out[:limit]


def _competitor_stats(
    workspace: GeoWorkspace,
    rows: list[GeoEvidence],
    question: GeoQuestionPlan,
) -> list[dict]:
    if not rows:
        return []
    comparison = build_competitor_comparison(workspace, rows, [question], evidence_limit=100)
    return [
        {
            "key": brand["key"],
            "name": brand["canonical_name"],
            "aliases": brand["aliases"],
            "appearances": brand["hit_answer_count"],
            "appearance_rate": brand["mention_rate"],
            "candidate_count": brand["candidate_count"],
            "recommendation_count": brand["recommendation_count"],
            "average_position": brand["explicit_average_position"],
            "top3_count": brand["top3_count"],
            "top3_rate": brand["top3_rate"],
            "wins_over_brand": brand["wins_over_baseline"],
            "comparable_answers": brand["comparable_answers"],
            "evidence_ids": sorted(
                {item["evidence_id"] for item in brand["evidence"]}, reverse=True
            ),
            "is_baseline": brand["is_baseline"],
        }
        for brand in comparison["brands"]
        if not brand["is_baseline"] and brand["hit_answer_count"] > 0
    ]


def _evidence_preview(row: GeoEvidence) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "model_key": row.model_key,
        "model_label": row.model_label,
        "brand_status": row.brand_status,
        "brand_position": row.brand_position,
        "answer_preview": " ".join((row.answer_text or "").split())[:220],
        "source_count": len(row.source_items or []),
        "captured_at": row.captured_at,
    }


def _model_stats(rows: list[GeoEvidence]) -> list[dict]:
    grouped: dict[str, list[GeoEvidence]] = defaultdict(list)
    for row in rows:
        grouped[row.model_key].append(row)
    output = []
    for key, model_rows in sorted(grouped.items(), key=lambda item: item[1][0].model_label):
        output.append(
            {
                "key": key,
                "label": model_rows[0].model_label,
                **_metric(model_rows),
                "latest_captured_at": max(row.captured_at for row in model_rows),
                "evidence_ids": [row.id for row in sorted(model_rows, key=lambda row: _utc(row.captured_at), reverse=True)],
            }
        )
    return output


def build_question_analysis(
    workspace: GeoWorkspace,
    question: GeoQuestionPlan,
    evidence_rows: list[GeoEvidence],
    *,
    scope: str,
    period_days: int | None,
    now: datetime | None = None,
) -> dict:
    """Build a reproducible analysis payload for one question.

    `current` means the most recent run containing this question.  A numeric
    scope is a rolling window and its comparison is the immediately preceding
    window of the same length.
    """
    now = _utc(now or datetime.now(timezone.utc))
    all_rows = sorted(
        [row for row in evidence_rows if row.is_real_provider_evidence and row.question_plan_id == question.id],
        key=lambda row: _utc(row.captured_at),
        reverse=True,
    )
    current_rows = all_rows
    previous_rows: list[GeoEvidence] = []
    scope_label = "当前测试"
    if scope == "current":
        if all_rows:
            latest_run_id = all_rows[0].run_id
            current_rows = [row for row in all_rows if row.run_id == latest_run_id]
            older = [row for row in all_rows if row.run_id != latest_run_id]
            if older:
                previous_run_id = older[0].run_id
                previous_rows = [row for row in older if row.run_id == previous_run_id]
        scope_label = "当前测试"
    else:
        days = period_days or int(scope)
        end = now
        start = end - timedelta(days=days)
        previous_start = start - timedelta(days=days)
        current_rows = [row for row in all_rows if start <= _utc(row.captured_at) <= end]
        previous_rows = [row for row in all_rows if previous_start <= _utc(row.captured_at) < start]
        scope_label = f"近 {days} 天"

    current_metric = _metric(current_rows)
    previous_metric = _metric(previous_rows)
    model_stats = _model_stats(current_rows)
    competitor_stats = _competitor_stats(workspace, current_rows, question)
    competitor_stats.sort(key=lambda item: (-item["wins_over_brand"], -item["appearances"], item["name"]))
    source_stats = _source_stats(current_rows)
    trend = []
    for label, rows in (("当前", current_rows), ("上一周期", previous_rows)):
        trend.append({"label": label, **_metric(rows)})
    return {
        "question": question,
        "scope": {
            "kind": scope,
            "label": scope_label,
            "period_days": period_days,
            "real_provider_evidence_only": True,
            "current_run_ids": sorted({row.run_id for row in current_rows}),
            "previous_run_ids": sorted({row.run_id for row in previous_rows}),
        },
        "summary": current_metric,
        "comparison": {"current": current_metric, "previous": previous_metric, "delta": _delta(current_metric, previous_metric)},
        "models": model_stats,
        "competitors": competitor_stats,
        "sources": source_stats,
        "trend": trend,
        "evidence": [_evidence_preview(row) for row in current_rows[:50]],
        "methodology": {
            "scope": "当前测试只使用该问题最近一次批次；日期范围使用当前时间窗口，且只纳入真实提供方证据。",
            "mention": "品牌状态为提及、候选、推荐、引用或负面时计入提及；同一回答计一次。",
            "competitor": "按回答原文中的明确编号/表格位置和候选/推荐上下文解析；不把文本出现顺序当排名。",
            "source": "同一回答内同一 URL 去重；信源偏好按不同模型引用该 URL 的回答次数统计。",
            "improvement": "变化值 = 当前范围指标 - 上一等长范围指标；平均位置下降代表排名变好。",
        },
    }
