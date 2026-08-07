"""WebSocket boundary for the Article Sync Assistant browser extension."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol
from uuid import uuid4

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect


DEFAULT_ARTICLE_SYNC_MCP_URL = "ws://localhost:9527"


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
    """Adapter for WechatSync's token-authenticated JSON messages over WebSocket.

    The extension does not expose an HTTP ``tools/call`` endpoint. It accepts
    ``{id, token, method, params}`` and replies with ``{id, result, error}``.
    """

    endpoint: str
    token: str
    timeout_seconds: float = 60.0

    def _call(self, method: str, params: dict) -> dict:
        request_id = str(uuid4())
        payload = {"id": request_id, "token": self.token, "method": method, "params": params}
        try:
            with connect(
                self.endpoint,
                open_timeout=min(10.0, self.timeout_seconds),
                close_timeout=5.0,
                max_size=8 * 1024 * 1024,
            ) as websocket:
                websocket.send(json.dumps(payload, ensure_ascii=False))
                raw = websocket.recv(timeout=self.timeout_seconds)
        except (OSError, TimeoutError, WebSocketException, ValueError) as exc:
            raise RuntimeError(f"article_sync_mcp_request_failed:{type(exc).__name__}") from exc
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("article_sync_mcp_invalid_response") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("article_sync_mcp_invalid_response")
        if parsed.get("error"):
            raise RuntimeError("article_sync_mcp_tool_error")
        result = parsed.get("result")
        return result if isinstance(result, dict) else {"result": result}

    def probe(self) -> dict:
        # Capability discovery is read-only and never creates a draft.
        result = self._call("listPlatforms", {"forceRefresh": True})
        return {"probe_status": "mcp_connected", "platforms": result}

    def request_draft(self, *, platform_key: str, title: str, body_markdown: str) -> dict:
        result = self._call(
            "syncArticle",
            {
                "platforms": [platform_key],
                "article": {"title": title, "markdown": body_markdown},
            },
        )
        return {"request_status": "mcp_request_accepted", "result": result}

    def read_draft(self, *, platform_key: str, candidate_url: str | None = None) -> dict:
        # The extension protocol has no readDraft method. Browser-side draft
        # readback remains a required, separate acceptance step.
        raise RuntimeError("article_sync_mcp_readback_requires_browser")


def get_article_sync_adapter(*, endpoint: str | None, token: str | None) -> ArticleSyncAdapter:
    """Return a real transport only after the extension token is configured."""

    if not token:
        return UnconfiguredArticleSyncAdapter()
    return McpArticleSyncAdapter(
        endpoint=(endpoint or DEFAULT_ARTICLE_SYNC_MCP_URL).strip(),
        token=token,
    )
