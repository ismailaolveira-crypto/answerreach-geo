"""Safe, actionable Agent failure messages for workspace-facing APIs."""

from __future__ import annotations


GENERIC_AGENT_FAILURE = (
    "Agent 本轮执行失败，未产生可用结果，也未修改原始证据。"
    "请稍后重试；如持续发生，请在运营状态中按任务号排查。"
)


def public_agent_error(message: str | None) -> str | None:
    """Hide runtime payloads while preserving concise operator-facing errors."""

    if not message:
        return None
    normalized = " ".join(str(message).split())
    lowered = normalized.lower()
    if "error_max_structured_output_retries" in lowered:
        return (
            "Agent 连续返回了未通过结构校验的结果，本次未产生新机会，"
            "也未修改原始证据。请稍后重试。"
        )
    if "timed out" in lowered or "timeout" in lowered:
        return "Agent 本轮执行超时，未产生可用结果。请稍后重试。"
    if normalized.startswith("{") or len(normalized) > 500:
        return GENERIC_AGENT_FAILURE
    return normalized
