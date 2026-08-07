"""Adapter for the official WechatSync MCP Server stdio transport.

The Chrome extension connects *to* the MCP Server over WebSocket. GEO talks
to the MCP Server over its standard MCP stdio transport; it must not connect
to the extension bridge directly.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from typing import Protocol


DEFAULT_MCP_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_NODE_BINARY = "node"


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
class StdioMcpArticleSyncAdapter:
    """Call the official ``@wechatsync/mcp-server`` through MCP stdio."""

    server_path: str
    token: str
    timeout_seconds: float = 20.0
    node_binary: str = DEFAULT_NODE_BINARY

    def _request(self, method: str, params: dict | None = None, request_id: int = 1) -> dict:
        path = Path(self.server_path).expanduser()
        if not path.is_file():
            raise RuntimeError("article_sync_mcp_server_path_not_found")

        env = os.environ.copy()
        # The token is passed only to the child process environment and is
        # never included in logs, URLs, responses, or exception messages.
        env["MCP_TOKEN"] = self.token
        process: subprocess.Popen[str] | None = None
        selector: selectors.BaseSelector | None = None
        try:
            process = subprocess.Popen(
                [self.node_binary, str(path)],
                cwd=str(path.parent),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("article_sync_mcp_stdio_unavailable")
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)

            self._send(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": DEFAULT_MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "geo-platform", "version": "0.1.0"},
            }})
            initialized = self._read_response(process, selector, 1)
            if initialized.get("error"):
                raise RuntimeError("article_sync_mcp_initialize_failed")
            self._send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._send(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
            response = self._read_response(process, selector, request_id)
            if response.get("error"):
                raise RuntimeError("article_sync_mcp_tool_error")
            result = response.get("result")
            return result if isinstance(result, dict) else {"result": result}
        except FileNotFoundError as exc:
            raise RuntimeError("article_sync_mcp_node_not_found") from exc
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError("article_sync_mcp_stdio_request_failed") from exc
        finally:
            if selector is not None:
                selector.close()
            if process is not None:
                if process.stdin is not None:
                    process.stdin.close()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)

    @staticmethod
    def _send(process: subprocess.Popen[str], message: dict) -> None:
        if process.stdin is None:
            raise RuntimeError("article_sync_mcp_stdio_unavailable")
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _read_response(
        self,
        process: subprocess.Popen[str],
        selector: selectors.BaseSelector,
        request_id: int,
    ) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            events = selector.select(timeout=remaining)
            if not events:
                continue
            line = process.stdout.readline() if process.stdout is not None else ""
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
        raise RuntimeError("article_sync_mcp_timeout")

    def _call_tool(self, name: str, arguments: dict) -> dict:
        return self._request("tools/call", {"name": name, "arguments": arguments}, request_id=2)

    def probe(self) -> dict:
        # ``list_platforms`` is read-only and also proves the extension bridge
        # is actually connected; no draft is created by this probe.
        platforms_result = self._call_tool("list_platforms", {"forceRefresh": True})
        if platforms_result.get("isError") is True:
            raise RuntimeError("article_sync_extension_not_connected")
        return {"probe_status": "mcp_connected", "platforms": platforms_result.get("content", platforms_result)}

    def request_draft(self, *, platform_key: str, title: str, body_markdown: str) -> dict:
        result = self._call_tool(
            "sync_article",
            {"platforms": [platform_key], "title": title, "markdown": body_markdown},
        )
        return {"request_status": "mcp_request_accepted", "result": result}

    def read_draft(self, *, platform_key: str, candidate_url: str | None = None) -> dict:
        # The official MCP tools do not read a saved draft back. Browser-side
        # readback remains a separate, required acceptance step.
        raise RuntimeError("article_sync_mcp_readback_requires_browser")


def get_article_sync_adapter(*, server_path: str | None, token: str | None) -> ArticleSyncAdapter:
    """Return a real transport only after both MCP Server path and token exist."""

    if not server_path or not token:
        return UnconfiguredArticleSyncAdapter()
    return StdioMcpArticleSyncAdapter(server_path=server_path.strip(), token=token)
