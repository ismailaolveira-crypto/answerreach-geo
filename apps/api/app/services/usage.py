from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LLMProvider, UsageRecord


VOLCENGINE_MONTHLY_SEARCH_ACTIONS = ("provider.test", "crawl.answer")


def enforce_monthly_search_budget(
    db: Session,
    provider: LLMProvider,
    *,
    projected_calls: int = 1,
) -> dict[str, int] | None:
    """Protect the Volcengine free Web Search allowance with a local hard cap."""
    if provider.provider_type != "volcengine_ark":
        return None
    limit = int((provider.cost_rule or {}).get("monthly_search_limit") or 0)
    if limit <= 0:
        return None
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = int(db.scalar(
        select(func.count(UsageRecord.id)).where(
            UsageRecord.provider_id == provider.id,
            UsageRecord.created_at >= month_start,
            UsageRecord.action.in_(VOLCENGINE_MONTHLY_SEARCH_ACTIONS),
        )
    ) or 0)
    requested = max(1, int(projected_calls))
    if used + requested > limit:
        raise ValueError(
            f"火山方舟本月联网调用已达到安全上限 {limit} 次；为避免超过免费额度产生费用，系统已停止调用。"
        )
    return {"used": used, "limit": limit, "remaining": limit - used - requested}


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    # Mixed Chinese/English approximation. Real providers should override with API usage.
    return max(1, round(len(text) / 2))


def estimate_cost(
    provider: LLMProvider | None, prompt_tokens: int, completion_tokens: int
) -> tuple[float, str]:
    if provider is None:
        return 0.0, "USD"
    cost_rule = provider.cost_rule or {}
    input_per_1k = float(cost_rule.get("input_per_1k", 0) or 0)
    output_per_1k = float(cost_rule.get("output_per_1k", 0) or 0)
    currency = str(cost_rule.get("currency", "USD") or "USD")
    cost = (prompt_tokens / 1000 * input_per_1k) + (completion_tokens / 1000 * output_per_1k)
    return round(cost, 6), currency


def record_usage(
    db: Session,
    *,
    provider: LLMProvider | None,
    action: str,
    prompt_text: str | None = None,
    completion_text: str | None = None,
    company_id: int | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    crawl_result_id: int | None = None,
    provider_test_run_id: int | None = None,
    detail: dict | None = None,
) -> UsageRecord:
    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = estimate_tokens(completion_text)
    estimated_cost, currency = estimate_cost(provider, prompt_tokens, completion_tokens)
    record = UsageRecord(
        provider_id=provider.id if provider else None,
        company_id=company_id,
        project_id=project_id,
        task_id=task_id,
        crawl_result_id=crawl_result_id,
        provider_test_run_id=provider_test_run_id,
        action=action,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        estimated_cost=estimated_cost,
        currency=currency,
        detail_json=detail or {},
    )
    db.add(record)
    db.flush()
    return record
