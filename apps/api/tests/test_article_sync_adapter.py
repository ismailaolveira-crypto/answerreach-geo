import json

import pytest

from app.services.article_sync_adapter import StdioMcpArticleSyncAdapter, _child_environment


def mcp_result(payload: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def test_mcp_child_receives_only_runtime_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/safe/bin")
    monkeypatch.setenv("HOME", "/safe/home")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-child")
    monkeypatch.setenv("AUTH_SECRET", "must-not-reach-child")

    environment = _child_environment("workspace-bridge-token")

    assert environment["PATH"] == "/safe/bin"
    assert environment["HOME"] == "/safe/home"
    assert environment["MCP_TOKEN"] == "workspace-bridge-token"
    assert "OPENAI_API_KEY" not in environment
    assert "DATABASE_URL" not in environment
    assert "AUTH_SECRET" not in environment


def test_probe_decodes_authenticated_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict, float]] = []

    def fake_call(self, name: str, arguments: dict, *, timeout_seconds: float) -> dict:
        calls.append((name, arguments, timeout_seconds))
        return mcp_result(
            [{"id": "weixin", "name": "微信公众号", "isAuthenticated": True}]
        )

    monkeypatch.setattr(StdioMcpArticleSyncAdapter, "_call_tool", fake_call)
    adapter = StdioMcpArticleSyncAdapter(server_path="/unused/index.js", token="test")

    result = adapter.probe()

    assert result["platforms"] == [
        {"id": "weixin", "name": "微信公众号", "isAuthenticated": True}
    ]
    assert calls == [("list_platforms", {"forceRefresh": True}, 180.0)]


def test_request_draft_rejects_expired_platform_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            mcp_result(
                [{"id": "weixin", "name": "微信公众号", "isAuthenticated": True}]
            ),
            mcp_result(
                {
                    "syncId": "sync-test",
                    "results": [
                        {
                            "platform": "weixin",
                            "success": False,
                            "error": "登录态超时，请重新登录",
                        }
                    ],
                }
            ),
        ]
    )

    def fake_call(
        self,
        name: str,
        arguments: dict,
        *,
        timeout_seconds: float = 360.0,
    ) -> dict:
        return next(responses)

    monkeypatch.setattr(StdioMcpArticleSyncAdapter, "_call_tool", fake_call)
    adapter = StdioMcpArticleSyncAdapter(server_path="/unused/index.js", token="test")

    with pytest.raises(RuntimeError, match="article_sync_platform_session_expired"):
        adapter.request_draft(
            platform_key="weixin",
            title="测试草稿",
            body_markdown="仅保存草稿。",
        )
