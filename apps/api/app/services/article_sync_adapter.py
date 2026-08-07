"""Persistent adapter for the official WechatSync MCP Server.

The Chrome extension is a WebSocket client. It needs a long-lived MCP Server
process to connect to; starting one process per tool call races the extension's
reconnect loop and makes a healthy extension look disconnected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import threading
import time
from typing import Protocol


DEFAULT_MCP_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_NODE_BINARY = "node"
DEFAULT_EXTENSION_BRIDGE_PORT = 9527
DEFAULT_EXTENSION_WAIT_SECONDS = 35.0
DEFAULT_TOOL_TIMEOUT_SECONDS = 360.0


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


@dataclass
class _StdioMcpSession:
    """One long-lived MCP stdio session owned by the API process."""

    server_path: str
    token: str
    node_binary: str = DEFAULT_NODE_BINARY
    _process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _selector: selectors.BaseSelector | None = field(default=None, init=False, repr=False)
    _next_request_id: int = field(default=1, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @property
    def fingerprint(self) -> str:
        material = f"{self.node_binary}\0{self.server_path}\0{self.token}".encode()
        return sha256(material).hexdigest()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def call_tool(
        self,
        name: str,
        arguments: dict,
        *,
        timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    ) -> dict:
        with self._lock:
            self._ensure_started_locked()
            request_id = self._new_request_id_locked()
            try:
                self._send_locked(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    }
                )
                response = self._read_response_locked(request_id, timeout_seconds)
            except RuntimeError:
                self._stop_locked()
                raise
            if response.get("error"):
                raise RuntimeError("article_sync_mcp_tool_error")
            result = response.get("result")
            return result if isinstance(result, dict) else {"result": result}

    def close(self) -> None:
        with self._lock:
            self._stop_locked()

    def _ensure_started_locked(self) -> None:
        if self.running:
            return
        self._stop_locked()
        path = Path(self.server_path).expanduser()
        if not path.is_file():
            raise RuntimeError("article_sync_mcp_server_path_not_found")
        if _tcp_port_is_open(DEFAULT_EXTENSION_BRIDGE_PORT):
            raise RuntimeError("article_sync_mcp_port_in_use")

        env = os.environ.copy()
        # The token stays in the child environment and is never included in
        # command arguments, URLs, responses, or diagnostic messages.
        env["MCP_TOKEN"] = self.token
        try:
            self._process = subprocess.Popen(
                [self.node_binary, str(path)],
                cwd=str(path.parent),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("article_sync_mcp_node_not_found") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("article_sync_mcp_start_failed") from exc

        if self._process.stdin is None or self._process.stdout is None:
            self._stop_locked()
            raise RuntimeError("article_sync_mcp_stdio_unavailable")
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._process.stdout, selectors.EVENT_READ)

        request_id = self._new_request_id_locked()
        try:
            self._send_locked(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": DEFAULT_MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "geo-platform", "version": "0.1.0"},
                    },
                }
            )
            initialized = self._read_response_locked(request_id, 20.0)
            if initialized.get("error"):
                raise RuntimeError("article_sync_mcp_initialize_failed")
            self._send_locked(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        except RuntimeError:
            self._stop_locked()
            raise

    def _new_request_id_locked(self) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    def _send_locked(self, message: dict) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("article_sync_mcp_stdio_unavailable")
        try:
            self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise RuntimeError("article_sync_mcp_stdio_request_failed") from exc

    def _read_response_locked(self, request_id: int, timeout_seconds: float) -> dict:
        if self._process is None or self._process.stdout is None or self._selector is None:
            raise RuntimeError("article_sync_mcp_stdio_unavailable")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            events = self._selector.select(timeout=remaining)
            if not events:
                continue
            line = self._process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
        raise RuntimeError("article_sync_mcp_timeout")

    def _stop_locked(self) -> None:
        selector, process = self._selector, self._process
        self._selector = None
        self._process = None
        if selector is not None:
            selector.close()
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


class _ArticleSyncRuntime:
    """Own the single local bridge process bound to port 9527."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: _StdioMcpSession | None = None

    def session_for(self, *, server_path: str, token: str) -> _StdioMcpSession:
        candidate = _StdioMcpSession(server_path=server_path, token=token)
        with self._lock:
            if self._session is not None and self._session.fingerprint == candidate.fingerprint:
                return self._session
            if self._session is not None:
                self._session.close()
            self._session = candidate
            return candidate

    def shutdown(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None


_RUNTIME = _ArticleSyncRuntime()


@dataclass(frozen=True)
class StdioMcpArticleSyncAdapter:
    """Call the managed official ``@wechatsync/mcp-server`` session."""

    server_path: str
    token: str
    extension_wait_seconds: float = DEFAULT_EXTENSION_WAIT_SECONDS

    def _call_tool(
        self,
        name: str,
        arguments: dict,
        *,
        timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    ) -> dict:
        session = _RUNTIME.session_for(server_path=self.server_path, token=self.token)
        return session.call_tool(name, arguments, timeout_seconds=timeout_seconds)

    def _wait_for_extension(self, *, force_refresh: bool) -> list[dict]:
        # The extension reconnects every 10 seconds when it has never reached
        # a server, then backs off further. Keep the MCP process alive and
        # retry across the first two cold reconnect windows.
        deadline = time.monotonic() + self.extension_wait_seconds
        while True:
            result = self._call_tool(
                "list_platforms",
                {"forceRefresh": force_refresh},
                # WechatSync checks 20+ platform sessions in batches. A cold
                # auth cache can legitimately take well beyond 20 seconds.
                timeout_seconds=180.0,
            )
            if result.get("isError") is not True:
                payload = _decode_tool_payload(result)
                return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
            error_code = _classify_tool_error(result)
            if error_code != "article_sync_extension_not_connected":
                raise RuntimeError(error_code)
            if time.monotonic() >= deadline:
                raise RuntimeError(error_code)
            time.sleep(0.5)

    def probe(self) -> dict:
        return {
            "probe_status": "mcp_connected",
            "platforms": self._wait_for_extension(force_refresh=True),
        }

    def request_draft(self, *, platform_key: str, title: str, body_markdown: str) -> dict:
        platforms = self._wait_for_extension(force_refresh=True)
        matching_platform = next(
            (item for item in platforms if item.get("id") == platform_key),
            None,
        )
        if matching_platform is None:
            raise RuntimeError("article_sync_platform_not_found")
        if matching_platform.get("isAuthenticated") is not True:
            raise RuntimeError("article_sync_platform_not_authenticated")
        result = self._call_tool(
            "sync_article",
            {"platforms": [platform_key], "title": title, "markdown": body_markdown},
        )
        if result.get("isError") is True:
            raise RuntimeError(_classify_tool_error(result))
        payload = _decode_tool_payload(result)
        platform_results = payload.get("results", []) if isinstance(payload, dict) else []
        platform_result = next(
            (
                item
                for item in platform_results
                if isinstance(item, dict) and item.get("platform") == platform_key
            ),
            None,
        )
        if not isinstance(platform_result, dict):
            raise RuntimeError("article_sync_draft_write_failed")
        if platform_result.get("success") is not True:
            error_text = str(platform_result.get("error") or "").lower()
            if "登录态超时" in error_text or "重新登录" in error_text or "请先登录" in error_text:
                raise RuntimeError("article_sync_platform_session_expired")
            raise RuntimeError("article_sync_draft_write_failed")
        return {
            "request_status": "mcp_request_accepted",
            "platform": platform_key,
            "platform_name": matching_platform.get("name") or platform_key,
            "sync_id": payload.get("syncId") if isinstance(payload, dict) else None,
            "draft_only": platform_result.get("draftOnly", True),
            "post_id": platform_result.get("postId"),
            "post_url": platform_result.get("postUrl"),
        }

    def read_draft(self, *, platform_key: str, candidate_url: str | None = None) -> dict:
        # The official MCP tools do not read a saved draft back. Browser-side
        # readback remains a separate, required acceptance step.
        raise RuntimeError("article_sync_mcp_readback_requires_browser")


def _classify_tool_error(result: dict) -> str:
    text = json.dumps(result.get("content", result), ensure_ascii=False).lower()
    if "extension 未连接" in text or "extension not connected" in text:
        return "article_sync_extension_not_connected"
    if "token" in text or "unauthorized" in text or "forbidden" in text:
        return "article_sync_mcp_auth_failed"
    return "article_sync_mcp_tool_error"


def _decode_tool_payload(result: dict) -> object:
    """Decode the official MCP tool's JSON text content without leaking it."""

    content = result.get("content")
    if not isinstance(content, list):
        return result
    for item in content:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        try:
            return json.loads(item["text"])
        except json.JSONDecodeError:
            continue
    return content


def _tcp_port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def shutdown_article_sync_runtime() -> None:
    _RUNTIME.shutdown()


def get_article_sync_adapter(*, server_path: str | None, token: str | None) -> ArticleSyncAdapter:
    """Return a managed transport only after path and token are configured."""

    if not server_path or not token:
        return UnconfiguredArticleSyncAdapter()
    return StdioMcpArticleSyncAdapter(server_path=server_path.strip(), token=token)
