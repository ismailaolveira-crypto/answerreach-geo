"""On-demand, scope-bound competitor analysis using DeepSeek.

The model never invents telemetry.  It receives only an already-filtered
comparison payload plus a small set of evidence snippets and must cite the
archived evidence IDs it used.  The generator has no persistence side effects;
the API stores its result as a derived report snapshot, never as observation
evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

import httpx


DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_INSIGHT_MODEL = "deepseek-chat"


class CompetitorInsightError(ValueError):
    """A safe, user-facing failure while preparing or generating an insight."""


def _plain_text(value: object, *, limit: int = 420) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _unique_evidence(comparison: dict[str, Any], *, limit: int = 16) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[int] = set()
    for brand in comparison.get("brands", []):
        for row in [*(brand.get("win_evidence") or []), *(brand.get("evidence") or [])]:
            evidence_id = row.get("evidence_id")
            if not isinstance(evidence_id, int) or evidence_id in seen:
                continue
            seen.add(evidence_id)
            output.append(
                {
                    "evidence_id": evidence_id,
                    "question": _plain_text(row.get("question"), limit=180),
                    "model": _plain_text(row.get("model_label"), limit=100),
                    "brand": _plain_text(row.get("brand_name"), limit=100),
                    "signal": _plain_text(row.get("win_reason_type") or row.get("status"), limit=80),
                    "excerpt": _plain_text(row.get("context_snippet"), limit=420),
                }
            )
            if len(output) >= limit:
                return output
    return output


def _comparison_context(
    comparison: dict[str, Any],
    *,
    selected_question_id: int | None,
    selected_question_label: str,
    selected_model_label: str,
    selected_period_label: str,
) -> tuple[dict[str, Any], set[int]]:
    brands = []
    for brand in comparison.get("brands", []):
        brands.append(
            {
                "name": brand.get("canonical_name"),
                "is_baseline": brand.get("is_baseline"),
                "hit_answers": brand.get("hit_answer_count"),
                "sample_answers": brand.get("sample_answer_count"),
                "mention_rate": brand.get("mention_rate"),
                "candidate_count": brand.get("candidate_count"),
                "recommendation_count": brand.get("recommendation_count"),
                "explicit_average_position": brand.get("explicit_average_position"),
                "wins_over_baseline": brand.get("wins_over_baseline"),
                "comparable_answers": brand.get("comparable_answers"),
            }
        )
    evidence = _unique_evidence(comparison)
    scope_kind = "单个问题" if selected_question_id is not None else "全部问题"
    diagnostics = comparison.get("action_diagnostics") or []
    if selected_question_id is None:
        # The overall view must stay aggregate. Do not turn one question into its headline.
        diagnostic_rollup: dict[str, dict[str, Any]] = {}
        for item in diagnostics:
            key = str(item.get("competitor_key") or item.get("competitor_name") or "unknown")
            bucket = diagnostic_rollup.setdefault(
                key,
                {"competitor": item.get("competitor_name"), "signal_count": 0, "question_count": set(), "model_count": set()},
            )
            bucket["signal_count"] += int(item.get("wins_over_baseline") or 0)
            bucket["question_count"].add(item.get("question_plan_id"))
            bucket["model_count"].add(item.get("model_key"))
        diagnostic_context = [
            {
                "competitor": item["competitor"],
                "signal_count": item["signal_count"],
                "question_count": len(item["question_count"] - {None}),
                "model_count": len(item["model_count"] - {None}),
            }
            for item in diagnostic_rollup.values()
        ]
    else:
        diagnostic_context = [
            {
                "competitor": item.get("competitor_name"),
                "signal_count": item.get("wins_over_baseline"),
                "reason": item.get("reason_label"),
                "comparable_answers": item.get("comparable_answers"),
            }
            for item in diagnostics
        ]
    return (
        {
            "scope": {
                "kind": scope_kind,
                "period": selected_period_label,
                "model": selected_model_label,
                "question": selected_question_label,
                "answer_count": comparison.get("summary", {}).get("answer_count", 0),
                "real_provider_evidence_only": True,
            },
            "brand_metrics": brands,
            "question_breakdown": [
                {"question": item.get("label"), "answer_count": item.get("answer_count")}
                for item in comparison.get("by_question", [])
            ],
            "comparison_signals": diagnostic_context,
            "evidence": evidence,
        },
        {item["evidence_id"] for item in evidence},
    )


def _parse_model_json(content: str, allowed_evidence_ids: set[int]) -> dict[str, Any]:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise CompetitorInsightError("DeepSeek 未返回可验证的结构化分析，请重试。") from error
    if not isinstance(payload, dict):
        raise CompetitorInsightError("DeepSeek 返回格式不正确，请重试。")

    def text(name: str, limit: int) -> str:
        value = _plain_text(payload.get(name), limit=limit)
        if not value:
            raise CompetitorInsightError(f"DeepSeek 返回缺少 {name}，请重试。")
        return value

    findings = []
    for item in payload.get("findings", [])[:4]:
        if not isinstance(item, dict):
            continue
        title = _plain_text(item.get("title"), limit=80)
        detail = _plain_text(item.get("detail"), limit=340)
        if not title or not detail:
            continue
        ids = [item_id for item_id in item.get("evidence_ids", []) if isinstance(item_id, int) and item_id in allowed_evidence_ids]
        findings.append({"title": title, "detail": detail, "evidence_ids": list(dict.fromkeys(ids))[:3]})
    actions = [_plain_text(item, limit=220) for item in payload.get("recommended_actions", [])[:4]]
    actions = [item for item in actions if item]
    limitations = [_plain_text(item, limit=220) for item in payload.get("limitations", [])[:3]]
    limitations = [item for item in limitations if item]
    if not findings or not actions:
        raise CompetitorInsightError("DeepSeek 返回缺少可核验结论或行动建议，请重试。")
    return {
        "scope_summary": text("scope_summary", 260),
        "overall_assessment": text("overall_assessment", 480),
        "findings": findings,
        "recommended_actions": actions,
        "limitations": limitations or ["结论仅基于当前筛选范围内已归档的真实提供方回答。"],
    }


def generate_competitor_insight(
    comparison: dict[str, Any],
    *,
    api_key: str | None,
    selected_question_id: int | None,
    selected_question_label: str,
    selected_model_label: str,
    selected_period_label: str,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    if not api_key:
        raise CompetitorInsightError("尚未配置 DeepSeek API Key。")
    context, allowed_evidence_ids = _comparison_context(
        comparison,
        selected_question_id=selected_question_id,
        selected_question_label=selected_question_label,
        selected_model_label=selected_model_label,
        selected_period_label=selected_period_label,
    )
    if not context["scope"]["answer_count"]:
        raise CompetitorInsightError("当前筛选范围没有真实回答，无法生成分析。")
    system_prompt = (
        "你是严谨的 GEO 竞争情报分析师。只能依据用户提供的 JSON 数据进行归纳，绝不联网、绝不补充外部事实、"
        "绝不把相关性说成因果。范围是硬约束：scope.kind 为‘全部问题’时必须给出全部问题的聚合分析，"
        "不能把任何一个单题写成总体结论；scope.kind 为‘单个问题’时才可讨论该题。"
        "所有量化结论必须与输入数字一致。证据只能引用 evidence 数组已有的 evidence_id；若无法支撑，请明确不确定。"
        "返回严格 JSON，不要 Markdown："
        '{"scope_summary":"...","overall_assessment":"...","findings":[{"title":"...","detail":"...","evidence_ids":[1]}],'
        '"recommended_actions":["..."],"limitations":["..."]}'
    )
    user_prompt = "请分析以下已归档数据：\n" + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    payload = {
        "model": DEEPSEEK_INSIGHT_MODEL,
        "temperature": 0.2,
        "max_tokens": 1300,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0), transport=transport) as client:
            response = client.post(
                DEEPSEEK_CHAT_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as error:
        raise CompetitorInsightError("DeepSeek 分析请求失败，请检查网络、额度或 API Key。") from error
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise CompetitorInsightError("DeepSeek 未返回分析内容，请重试。") from error
    if not isinstance(content, str):
        raise CompetitorInsightError("DeepSeek 返回内容格式不正确，请重试。")
    return {
        "provider": "DeepSeek",
        "model": DEEPSEEK_INSIGHT_MODEL,
        "generated_at": datetime.now(timezone.utc),
        "scope": context["scope"],
        "analysis": _parse_model_json(content, allowed_evidence_ids),
    }
