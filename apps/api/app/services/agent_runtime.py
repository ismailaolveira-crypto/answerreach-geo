"""Runtime-neutral Agent bridge for the GEO action workflow.

The database and workflow speak one small contract. Each runtime adapter owns
its native transport and must return the same structured turn result. Secrets
stay in the runtime's own environment/configuration and are never serialized.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from time import monotonic
from typing import Callable, Protocol
from uuid import uuid4

import httpx

from app.core.config import get_settings
from app.services.codex_agent_runtime import (
    CodexRunInterrupted,
    CodexRunTimedOut,
    CodexRuntimeUnavailable,
    CodexTurnResult,
    LocalCodexRuntime,
    diagnose_local_codex,
    invalidate_local_codex_diagnostic_cache,
)


RUNTIME_KEYS = ("local_codex", "claude_agent", "hermes", "openclaw")
DEFAULT_REASONING_EFFORTS = ["low", "medium", "high"]


class AgentRuntimeAdapter(Protocol):
    def run_structured(
        self,
        *,
        task_directory: Path,
        prompt: str,
        output_schema: dict,
        developer_instructions: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        thread_id: str | None = None,
        on_started: Callable[[str, str], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        timeout_seconds: float | None = 900.0,
    ) -> CodexTurnResult: ...


def sanitize_agent_error(error: object) -> str:
    message = str(error)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    anthropic_key = anthropic_key or get_settings().anthropic_api_key or ""
    if anthropic_key:
        message = message.replace(anthropic_key, "[secret]")
    hermes_key = get_settings().hermes_api_key or ""
    if hermes_key:
        message = message.replace(hermes_key, "[secret]")
    return message[:500]


def _runtime_metadata(runtime_key: str) -> dict:
    return {
        "local_codex": {
            "display_name": "Codex",
            "description": "OpenAI 官方本机 SDK，复用当前 ChatGPT 登录。",
            "logo_path": "/brand/openai.svg",
            "transport": "official_sdk",
            "configuration_hint": "在本机 Codex 完成 ChatGPT 登录。",
        },
        "claude_agent": {
            "display_name": "Claude Agent",
            "description": "Anthropic 官方 Agent SDK，使用下载者自己的 API 配置。",
            "logo_path": "/brand/claude.svg",
            "transport": "official_sdk",
            "configuration_hint": "配置 ANTHROPIC_API_KEY 后重启 API 与 worker。",
        },
        "hermes": {
            "display_name": "Hermes",
            "description": "通过 Hermes 官方 OpenAI 兼容 HTTP API 调用本机 Agent。",
            "logo_path": "/brand/hermes.svg",
            "transport": "http_api",
            "configuration_hint": "启动 Hermes API Server，并配置 HERMES_API_KEY。",
        },
        "openclaw": {
            "display_name": "OpenClaw",
            "description": "通过 OpenClaw 官方 headless Agent CLI 调用本机配置。",
            "logo_path": "/brand/openclaw.svg",
            "transport": "official_cli",
            "configuration_hint": "安装并完成 openclaw onboard，确保命令位于 API/worker 的 PATH。",
        },
    }[runtime_key]


def _with_metadata(runtime_key: str, diagnostic: dict) -> dict:
    return {**_runtime_metadata(runtime_key), **diagnostic, "runtime_key": runtime_key}


def _claude_models() -> list[dict]:
    models = [
        item.strip()
        for item in get_settings().claude_agent_models.split(",")
        if item.strip()
    ]
    return [
        {
            "id": model,
            "display_name": model,
            "description": "由 Claude Agent SDK 执行",
            "default_reasoning_effort": "medium",
            "supported_reasoning_efforts": ["low", "medium", "high", "xhigh"],
        }
        for model in models
    ]


def diagnose_claude_agent() -> dict:
    installed = importlib.util.find_spec("claude_agent_sdk") is not None
    configured = bool(get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
    options = _claude_models()
    return _with_metadata(
        "claude_agent",
        {
            "sdk_installed": installed,
            "sdk_version": None,
            "runtime_version": None,
            "ready": installed and configured and bool(options),
            "login_status": (
                "api_key_configured"
                if configured
                else "api_key_required" if installed else "sdk_missing"
            ),
            "default_model": options[0]["id"] if options else None,
            "default_reasoning_effort": "medium",
            "available_models": [item["id"] for item in options],
            "model_options": options,
            "connection_status": "cold",
            "connected_since": None,
            "reuse_count": 0,
            "error": None if installed and configured else (
                "未配置 ANTHROPIC_API_KEY" if installed else "未安装 Claude Agent SDK"
            ),
        },
    )


def _hermes_headers() -> dict[str, str]:
    key = get_settings().hermes_api_key
    return {"Authorization": f"Bearer {key}"} if key else {}


def diagnose_hermes() -> dict:
    settings = get_settings()
    base_url = settings.hermes_api_url.rstrip("/")
    if not settings.hermes_api_key:
        return _with_metadata(
            "hermes",
            {
                "sdk_installed": shutil.which("hermes") is not None,
                "ready": False,
                "login_status": "api_key_required",
                "available_models": [],
                "model_options": [],
                "connection_status": "cold",
                "error": "未配置 HERMES_API_KEY",
            },
        )
    try:
        with httpx.Client(timeout=3.0, headers=_hermes_headers()) as client:
            health = client.get(f"{base_url}/health")
            health.raise_for_status()
            response = client.get(f"{base_url}/v1/models")
            response.raise_for_status()
            rows = list(response.json().get("data") or [])
        models = [str(row.get("id") or "").strip() for row in rows]
        models = [value for value in models if value]
        options = [
            {
                "id": model,
                "display_name": model,
                "description": "由 Hermes API Server 提供",
                "default_reasoning_effort": "medium",
                "supported_reasoning_efforts": DEFAULT_REASONING_EFFORTS,
            }
            for model in models
        ]
        return _with_metadata(
            "hermes",
            {
                "sdk_installed": shutil.which("hermes") is not None,
                "ready": bool(models),
                "login_status": "api_authenticated",
                "default_model": models[0] if models else None,
                "default_reasoning_effort": "medium",
                "available_models": models,
                "model_options": options,
                "connection_status": "warm",
                "connected_since": None,
                "reuse_count": 0,
                "error": None if models else "Hermes 未返回可用模型",
            },
        )
    except Exception as exc:
        return _with_metadata(
            "hermes",
            {
                "sdk_installed": shutil.which("hermes") is not None,
                "ready": False,
                "login_status": "runtime_unreachable",
                "available_models": [],
                "model_options": [],
                "connection_status": "cold",
                "error": sanitize_agent_error(exc),
            },
        )


def _run_json_command(command: list[str], *, timeout: float = 8.0) -> dict:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "command failed")
    return json.loads(completed.stdout)


def diagnose_openclaw() -> dict:
    executable = shutil.which("openclaw")
    if not executable:
        return _with_metadata(
            "openclaw",
            {
                "sdk_installed": False,
                "ready": False,
                "login_status": "cli_missing",
                "available_models": [],
                "model_options": [],
                "connection_status": "cold",
                "error": "未安装 OpenClaw CLI，或 API/worker 的 PATH 中找不到 openclaw",
            },
        )
    try:
        payload = _run_json_command([executable, "models", "list", "--json"])
        rows = payload if isinstance(payload, list) else payload.get("models") or payload.get("data") or []
        models = []
        for row in rows:
            value = row if isinstance(row, str) else row.get("id") or row.get("key")
            if value:
                models.append(str(value))
        models = list(dict.fromkeys(models))
        options = [
            {
                "id": model,
                "display_name": model,
                "description": "由 OpenClaw 本机配置提供",
                "default_reasoning_effort": "medium",
                "supported_reasoning_efforts": DEFAULT_REASONING_EFFORTS,
            }
            for model in models
        ]
        return _with_metadata(
            "openclaw",
            {
                "sdk_installed": True,
                "ready": bool(models),
                "login_status": "local_profile_ready" if models else "onboarding_required",
                "default_model": models[0] if models else None,
                "default_reasoning_effort": "medium",
                "available_models": models,
                "model_options": options,
                "connection_status": "cold",
                "connected_since": None,
                "reuse_count": 0,
                "error": None if models else "OpenClaw 未返回可用模型，请先完成 onboard",
            },
        )
    except Exception as exc:
        return _with_metadata(
            "openclaw",
            {
                "sdk_installed": True,
                "ready": False,
                "login_status": "runtime_error",
                "available_models": [],
                "model_options": [],
                "connection_status": "cold",
                "error": sanitize_agent_error(exc),
            },
        )


def diagnose_agent_runtime(runtime_key: str, *, invalidate: bool = False) -> dict:
    if runtime_key not in RUNTIME_KEYS:
        raise KeyError(runtime_key)
    if runtime_key == "local_codex":
        if invalidate:
            invalidate_local_codex_diagnostic_cache()
        return _with_metadata("local_codex", diagnose_local_codex())
    if runtime_key == "claude_agent":
        return diagnose_claude_agent()
    if runtime_key == "hermes":
        return diagnose_hermes()
    return diagnose_openclaw()


def list_agent_runtimes() -> list[dict]:
    return [diagnose_agent_runtime(runtime_key) for runtime_key in RUNTIME_KEYS]


def _structured_prompt(prompt: str, developer_instructions: str, output_schema: dict) -> str:
    return (
        f"SYSTEM CONTRACT\n{developer_instructions}\n\n"
        f"TASK\n{prompt}\n\n"
        "Return only one JSON object matching this JSON Schema:\n"
        f"{json.dumps(output_schema, ensure_ascii=False)}"
    )


class ClaudeAgentRuntime:
    def run_structured(self, **kwargs) -> CodexTurnResult:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        task_directory = Path(kwargs["task_directory"]).resolve()
        task_directory.mkdir(parents=True, exist_ok=True)
        timeout_seconds = float(kwargs.get("timeout_seconds") or 900)
        started = kwargs.get("on_started")
        on_event = kwargs.get("on_event")
        thread_id = kwargs.get("thread_id")
        turn_id = f"claude-{uuid4()}"

        async def execute() -> CodexTurnResult:
            final: dict | None = None
            session_id = thread_id or ""
            usage: dict = {}
            options = ClaudeAgentOptions(
                cwd=task_directory,
                system_prompt=kwargs["developer_instructions"],
                model=kwargs.get("model"),
                effort=kwargs.get("reasoning_effort"),
                resume=thread_id,
                tools=["WebSearch", "WebFetch"],
                output_format={"type": "json_schema", "schema": kwargs["output_schema"]},
                strict_mcp_config=True,
                setting_sources=[],
                env={
                    **os.environ,
                    **(
                        {"ANTHROPIC_API_KEY": get_settings().anthropic_api_key}
                        if get_settings().anthropic_api_key
                        else {}
                    ),
                },
            )
            with anyio.fail_after(timeout_seconds):
                async for message in query(prompt=kwargs["prompt"], options=options):
                    if kwargs.get("cancellation_requested") and kwargs["cancellation_requested"]():
                        raise CodexRunInterrupted("Claude Agent run was interrupted by the user")
                    if on_event:
                        on_event("agent/message", {"type": type(message).__name__})
                    if isinstance(message, ResultMessage):
                        session_id = str(message.session_id or session_id)
                        final = message.structured_output
                        usage = dict(message.usage or {})
            if not session_id:
                session_id = f"claude-session-{uuid4()}"
            if started:
                started(session_id, turn_id)
            if final is None:
                raise CodexRuntimeUnavailable("Claude Agent returned no structured output")
            final_response = json.dumps(final, ensure_ascii=False)
            return CodexTurnResult(session_id, turn_id, final_response, usage, [])

        try:
            return anyio.run(execute)
        except TimeoutError as exc:
            raise CodexRunTimedOut(f"Claude Agent exceeded {timeout_seconds:g} seconds") from exc


class HermesRuntime:
    def run_structured(self, **kwargs) -> CodexTurnResult:
        settings = get_settings()
        base_url = settings.hermes_api_url.rstrip("/")
        timeout_seconds = float(kwargs.get("timeout_seconds") or 900)
        if kwargs.get("cancellation_requested") and kwargs["cancellation_requested"]():
            raise CodexRunInterrupted("Hermes run was interrupted before it began")
        body = {
            "model": kwargs.get("model"),
            "messages": [
                {"role": "system", "content": kwargs["developer_instructions"]},
                {
                    "role": "user",
                    "content": _structured_prompt(
                        kwargs["prompt"], kwargs["developer_instructions"], kwargs["output_schema"]
                    ),
                },
            ],
            "stream": False,
            "reasoning_effort": kwargs.get("reasoning_effort"),
        }
        headers = _hermes_headers()
        if kwargs.get("thread_id"):
            headers["X-Hermes-Session-Id"] = str(kwargs["thread_id"])
        try:
            with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
                response = client.post(f"{base_url}/v1/chat/completions", json=body)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise CodexRunTimedOut(f"Hermes exceeded {timeout_seconds:g} seconds") from exc
        except Exception as exc:
            raise CodexRuntimeUnavailable(sanitize_agent_error(exc)) from exc
        choice = (payload.get("choices") or [{}])[0]
        final_response = str((choice.get("message") or {}).get("content") or "")
        try:
            json.loads(final_response)
        except json.JSONDecodeError as exc:
            raise CodexRuntimeUnavailable("Hermes returned no valid structured JSON") from exc
        session_id = str(
            response.headers.get("X-Hermes-Session-Id")
            or kwargs.get("thread_id")
            or payload.get("session_id")
            or f"hermes-session-{uuid4()}"
        )
        turn_id = str(payload.get("id") or f"hermes-turn-{uuid4()}")
        if kwargs.get("on_started"):
            kwargs["on_started"](session_id, turn_id)
        return CodexTurnResult(session_id, turn_id, final_response, payload.get("usage") or {}, [])


class OpenClawRuntime:
    def run_structured(self, **kwargs) -> CodexTurnResult:
        executable = shutil.which("openclaw")
        if not executable:
            raise CodexRuntimeUnavailable("OpenClaw CLI is not installed")
        task_directory = Path(kwargs["task_directory"]).resolve()
        task_directory.mkdir(parents=True, exist_ok=True)
        prompt_path = task_directory / "openclaw-request.txt"
        prompt_path.write_text(
            _structured_prompt(
                kwargs["prompt"], kwargs["developer_instructions"], kwargs["output_schema"]
            ),
            encoding="utf-8",
        )
        timeout_seconds = max(1, int(kwargs.get("timeout_seconds") or 900))
        command = [
            executable,
            "agent",
            "--agent",
            get_settings().openclaw_agent_id,
            "--message-file",
            str(prompt_path),
            "--timeout",
            str(timeout_seconds),
            "--json",
        ]
        if kwargs.get("model"):
            command.extend(["--model", str(kwargs["model"])])
        if kwargs.get("reasoning_effort"):
            command.extend(["--thinking", str(kwargs["reasoning_effort"])])
        started_at = monotonic()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if kwargs.get("cancellation_requested") and kwargs["cancellation_requested"]():
                    process.terminate()
                    process.communicate()
                    raise CodexRunInterrupted("OpenClaw run was interrupted by the user")
                if monotonic() - started_at > timeout_seconds:
                    process.terminate()
                    process.communicate()
                    raise CodexRunTimedOut(f"OpenClaw exceeded {timeout_seconds:g} seconds")
        if process.returncode != 0:
            raise CodexRuntimeUnavailable(sanitize_agent_error(stderr or stdout or "OpenClaw run failed"))
        try:
            payload = json.loads(stdout)
            final_response = str(payload.get("final") or "")
            json.loads(final_response)
        except (json.JSONDecodeError, AttributeError) as exc:
            raise CodexRuntimeUnavailable("OpenClaw returned no valid structured JSON") from exc
        session_id = str(payload.get("sessionId") or kwargs.get("thread_id") or f"openclaw-{uuid4()}")
        turn_id = f"openclaw-turn-{uuid4()}"
        if kwargs.get("on_started"):
            kwargs["on_started"](session_id, turn_id)
        return CodexTurnResult(session_id, turn_id, final_response, payload.get("usage") or {}, [])


def get_agent_runtime(runtime_key: str) -> AgentRuntimeAdapter:
    if runtime_key == "local_codex":
        return LocalCodexRuntime()
    if runtime_key == "claude_agent":
        return ClaudeAgentRuntime()
    if runtime_key == "hermes":
        return HermesRuntime()
    if runtime_key == "openclaw":
        return OpenClawRuntime()
    raise KeyError(runtime_key)
