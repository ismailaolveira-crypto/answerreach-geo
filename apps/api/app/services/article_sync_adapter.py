"""Boundary for the article-sync assistant MCP integration.

The concrete MCP transport is intentionally injected by deployment. Keeping an
unconfigured adapter explicit prevents a queued request from being reported as
an external draft write when no request/readback has happened.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from uuid import uuid4
from typing import Protocol

import httpx


class ArticleSyncAdapter(Protocol):
    def probe(self) -> dict: ...

    def request_draft(self, *, platform_key: str, title: str, body_markdown: str) -> dict: ...

    def read_draft(self, *, platform_key: str, candidate_url: str | None = None) -> dict: ...


@dataclass(frozen=True)
class UnconfiguredArticleSyncAdapter:
    reason: str = "sync_adapter_not_configured"

    def probe(self) -> dict:
        raise RuntimeError(self.reason)

    def request_draft(self, *, platform_key: str, title: str, body_markdown: str) -> dict:
        raise RuntimeError(self.reason)

    def read_draft(self, *, platform_key: str, candidate_url: str | None = None) -> dict:
        raise RuntimeError(self.reason)


@dataclass(frozen=True)
class McpArticleSyncAdapter:
    endpoint: str
    token: str
    timeout_seconds: float = 60.0

    def probe(self) -> dict:
        # Capability discovery is read-only: it must never create a draft.
        result = self._call("list_platforms", {"forceRefresh": True})
        return {"probe_status": "mcp_connected", "platforms": result}

    def _call(self, tool_name: str, arguments: dict) -> dict:
        request_id = str(uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json=payload,
                )
                response.raise_for_status()
                body = response.text.strip()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"article_sync_mcp_request_failed:{type(exc).__name__}") from exc
        # MCP HTTP transports may return a JSON-RPC object or an SSE data frame.
        if body.startswith("data:"):
            body = next((line.removeprefix("data:").strip() for line in body.splitlines() if line.startswith("data:")), "")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("article_sync_mcp_invalid_response") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("article_sync_mcp_invalid_response")
        if parsed.get("error"):
            raise RuntimeError("article_sync_mcp_tool_error")
        result = parsed.get("result")
        return result if isinstance(result, dict) else {"result": result}

    def request_draft(self, *, platform_key: str, title: str, body_markdown: str) -> dict:
        result = self._call(
            "sync_article",
            {
                "platforms": [platform_key],
                "title": title,
                "markdown": body_markdown,
            },
        )
        return {"request_status": "mcp_request_accepted", "result": result}

    def read_draft(self, *, platform_key: str, candidate_url: str | None = None) -> dict:
        result = self._call(
            "read_draft",
            {"platform_key": platform_key, "candidate_url": candidate_url},
        )
        return {"readback_status": "readback_received", "result": result}


def get_article_sync_adapter(*, endpoint: str | None, token: str | None) -> ArticleSyncAdapter:
    """Return a real transport only after deployment supplies both secret refs.

    Token values are never logged, serialized, or returned to the API caller.
    """

    if not endpoint or not token:
        return UnconfiguredArticleSyncAdapter()
    return McpArticleSyncAdapter(endpoint=endpoint, token=token)
