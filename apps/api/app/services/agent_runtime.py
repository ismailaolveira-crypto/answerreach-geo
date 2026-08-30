"""Runtime-neutral Agent bridge for the GEO action workflow.

The database and workflow speak one small contract. Each runtime adapter owns
its native transport and must return the same structured turn result. Secrets
stay in the runtime's own environment/configuration and are never serialized.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import Lock
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
AGENT_DIAGNOSTIC_CACHE_TTL_SECONDS = 30.0
_agent_diagnostic_cache: dict[str, tuple[float, dict]] = {}
_agent_diagnostic_cache_lock = Lock()
_agent_diagnostic_runtime_locks = {runtime_key: Lock() for runtime_key in RUNTIME_KEYS}


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
            "display_name": "Claude Code",
            "description": "Anthropic 官方本机 CLI，复用下载者自己的 Claude 登录。",
            "logo_path": "/brand/claude.svg",
            "transport": "official_cli",
            "configuration_hint": "安装 Claude Code 并执行 claude auth login。",
        },
        "hermes": {
            "display_name": "Hermes",
            "description": "Hermes 官方本机 CLI，优先复用用户已选的 provider 和模型。",
            "logo_path": "/brand/hermes.svg",
            "transport": "official_cli",
            "configuration_hint": "安装 Hermes 并执行 hermes model 完成本机 provider 配置。",
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
            "description": "由本机 Claude Code CLI 执行",
            "default_reasoning_effort": "medium",
            "supported_reasoning_efforts": ["low", "medium", "high", "xhigh"],
        }
        for model in models
    ]


def _claude_environment() -> dict[str, str]:
    environment = dict(os.environ)
    configured_key = get_settings().anthropic_api_key
    if configured_key:
        environment["ANTHROPIC_API_KEY"] = configured_key
    return environment


def diagnose_claude_agent() -> dict:
    executable = shutil.which("claude")
    options = _claude_models()
    if not executable:
        return _with_metadata(
            "claude_agent",
            {
                "sdk_installed": False,
                "ready": False,
                "login_status": "cli_missing",
                "default_model": options[0]["id"] if options else None,
                "default_reasoning_effort": "medium",
                "available_models": [item["id"] for item in options],
                "model_options": options,
                "connection_status": "cold",
                "error": "未安装 Claude Code CLI，或 API/worker 的 PATH 中找不到 claude",
            },
        )
    try:
        auth = _run_json_command(
            [executable, "auth", "status", "--json"],
            env=_claude_environment(),
        )
        logged_in = auth.get("loggedIn") is True
        version = _run_text_command([executable, "--version"], timeout=5.0).strip()
    except Exception as exc:
        return _with_metadata(
            "claude_agent",
            {
                "sdk_installed": True,
                "ready": False,
                "login_status": "auth_check_failed",
                "default_model": options[0]["id"] if options else None,
                "default_reasoning_effort": "medium",
                "available_models": [item["id"] for item in options],
                "model_options": options,
                "connection_status": "cold",
                "error": sanitize_agent_error(exc),
            },
        )
    return _with_metadata(
        "claude_agent",
        {
            "sdk_installed": True,
            "sdk_version": version or None,
            "runtime_version": version or None,
            "ready": logged_in and bool(options),
            "login_status": "local_cli_authenticated" if logged_in else "login_required",
            "default_model": options[0]["id"] if options else None,
            "default_reasoning_effort": "medium",
            "available_models": [item["id"] for item in options],
            "model_options": options,
            "connection_status": "warm" if logged_in else "cold",
            "connected_since": None,
            "reuse_count": 0,
            "error": None if logged_in else "Claude Code 尚未登录，请执行 claude auth login",
        },
    )


def _hermes_headers() -> dict[str, str]:
    key = get_settings().hermes_api_key
    return {"Authorization": f"Bearer {key}"} if key else {}


def _diagnose_hermes_http() -> dict:
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
                "transport": "http_api",
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
                "transport": "http_api",
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
                "transport": "http_api",
                "error": sanitize_agent_error(exc),
            },
        )


def _run_text_command(
    command: list[str],
    *,
    timeout: float = 8.0,
    env: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "command failed")
    return completed.stdout


def _run_json_command(
    command: list[str],
    *,
    timeout: float = 8.0,
    env: dict[str, str] | None = None,
) -> dict:
    return json.loads(_run_text_command(command, timeout=timeout, env=env))


def _hermes_status_value(status: str, label: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(label)}:\s*(.+?)\s*$", status, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _diagnose_hermes_cli(executable: str) -> dict:
    try:
        _run_text_command([executable, "config", "check"], timeout=8.0)
        status = _run_text_command([executable, "status", "--all"], timeout=8.0)
        model = _hermes_status_value(status, "Model")
        provider = _hermes_status_value(status, "Provider")
        version = _run_text_command([executable, "--version"], timeout=5.0).splitlines()[0].strip()
        if not model or not provider:
            raise RuntimeError("Hermes local profile has no default provider or model")
        option = {
            "id": model,
            "display_name": model,
            "description": f"Hermes 本机 {provider} profile",
            "default_reasoning_effort": None,
            "supported_reasoning_efforts": [],
        }
        return _with_metadata(
            "hermes",
            {
                "sdk_installed": True,
                "sdk_version": version or None,
                "runtime_version": version or None,
                "ready": True,
                "login_status": "local_profile_configured",
                "default_model": model,
                "default_reasoning_effort": None,
                "available_models": [model],
                "model_options": [option],
                "connection_status": "configured",
                "connected_since": None,
                "reuse_count": 0,
                "transport": "official_cli",
                "error": None,
            },
        )
    except Exception as exc:
        return _with_metadata(
            "hermes",
            {
                "sdk_installed": True,
                "ready": False,
                "login_status": "local_profile_invalid",
                "available_models": [],
                "model_options": [],
                "connection_status": "cold",
                "transport": "official_cli",
                "error": sanitize_agent_error(exc),
            },
        )


def diagnose_hermes() -> dict:
    executable = shutil.which("hermes")
    if executable:
        cli_diagnostic = _diagnose_hermes_cli(executable)
        if cli_diagnostic.get("ready") or not get_settings().hermes_api_key:
            return cli_diagnostic
    if get_settings().hermes_api_key:
        return _diagnose_hermes_http()
    return _with_metadata(
        "hermes",
        {
            "sdk_installed": False,
            "ready": False,
            "login_status": "cli_missing",
            "available_models": [],
            "model_options": [],
            "connection_status": "cold",
            "error": "未安装 Hermes CLI，或 API/worker 的 PATH 中找不到 hermes",
        },
    )


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


def _diagnose_agent_runtime_uncached(runtime_key: str) -> dict:
    if runtime_key == "local_codex":
        return _with_metadata("local_codex", diagnose_local_codex())
    if runtime_key == "claude_agent":
        return diagnose_claude_agent()
    if runtime_key == "hermes":
        return diagnose_hermes()
    return diagnose_openclaw()


def invalidate_agent_runtime_diagnostic_cache(runtime_key: str | None = None) -> None:
    if runtime_key is not None and runtime_key not in RUNTIME_KEYS:
        raise KeyError(runtime_key)
    with _agent_diagnostic_cache_lock:
        if runtime_key is None:
            _agent_diagnostic_cache.clear()
        else:
            _agent_diagnostic_cache.pop(runtime_key, None)
    if runtime_key in {None, "local_codex"}:
        invalidate_local_codex_diagnostic_cache()


def diagnose_agent_runtime(runtime_key: str, *, invalidate: bool = False) -> dict:
    if runtime_key not in RUNTIME_KEYS:
        raise KeyError(runtime_key)
    if invalidate:
        with _agent_diagnostic_runtime_locks[runtime_key]:
            invalidate_agent_runtime_diagnostic_cache(runtime_key)
            diagnostic = _diagnose_agent_runtime_uncached(runtime_key)
            with _agent_diagnostic_cache_lock:
                _agent_diagnostic_cache[runtime_key] = (monotonic(), deepcopy(diagnostic))
            return deepcopy(diagnostic)
    now = monotonic()
    with _agent_diagnostic_cache_lock:
        cached = _agent_diagnostic_cache.get(runtime_key)
        if cached and now - cached[0] < AGENT_DIAGNOSTIC_CACHE_TTL_SECONDS:
            return deepcopy(cached[1])

    # Only one caller may run a given CLI diagnostic at a time. Other runtimes
    # still diagnose in parallel through list_agent_runtimes().
    with _agent_diagnostic_runtime_locks[runtime_key]:
        now = monotonic()
        with _agent_diagnostic_cache_lock:
            cached = _agent_diagnostic_cache.get(runtime_key)
            if cached and now - cached[0] < AGENT_DIAGNOSTIC_CACHE_TTL_SECONDS:
                return deepcopy(cached[1])
        diagnostic = _diagnose_agent_runtime_uncached(runtime_key)
        with _agent_diagnostic_cache_lock:
            _agent_diagnostic_cache[runtime_key] = (monotonic(), deepcopy(diagnostic))
        return deepcopy(diagnostic)


def list_agent_runtimes() -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(RUNTIME_KEYS), thread_name_prefix="agent-diagnostic") as executor:
        diagnostics = {
            runtime_key: executor.submit(diagnose_agent_runtime, runtime_key)
            for runtime_key in RUNTIME_KEYS
        }
        return [diagnostics[runtime_key].result() for runtime_key in RUNTIME_KEYS]


def _structured_prompt(prompt: str, developer_instructions: str, output_schema: dict) -> str:
    return (
        f"SYSTEM CONTRACT\n{developer_instructions}\n\n"
        f"TASK\n{prompt}\n\n"
        "Return only one JSON object matching this JSON Schema:\n"
        f"{json.dumps(output_schema, ensure_ascii=False)}"
    )


def _stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    process.terminate()
    try:
        return process.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()


def _run_cancellable_cli(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    cancellation_requested: Callable[[], bool] | None,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    runtime_name: str,
) -> tuple[str, str, int]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if input_text is not None and process.stdin is not None:
        process.stdin.write(input_text)
        process.stdin.close()
        process.stdin = None
    started_at = monotonic()
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.25)
            return stdout, stderr, int(process.returncode or 0)
        except subprocess.TimeoutExpired:
            if cancellation_requested and cancellation_requested():
                _stop_process(process)
                raise CodexRunInterrupted(f"{runtime_name} run was interrupted by the user")
            if monotonic() - started_at > timeout_seconds:
                _stop_process(process)
                raise CodexRunTimedOut(f"{runtime_name} exceeded {timeout_seconds:g} seconds")


def _extract_json_object(value: str) -> dict:
    normalized = value.strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*```$", "", normalized)
    start = normalized.find("{")
    if start < 0:
        raise json.JSONDecodeError("no JSON object", normalized, 0)
    parsed, _end = json.JSONDecoder().raw_decode(normalized[start:])
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("expected JSON object", normalized, start)
    return parsed


class ClaudeCodeRuntime:
    def run_structured(self, **kwargs) -> CodexTurnResult:
        executable = shutil.which("claude")
        if not executable:
            raise CodexRuntimeUnavailable("Claude Code CLI is not installed")
        task_directory = Path(kwargs["task_directory"]).resolve()
        task_directory.mkdir(parents=True, exist_ok=True)
        timeout_seconds = float(kwargs.get("timeout_seconds") or 900)
        existing_session = str(kwargs.get("thread_id") or "") or None
        session_id = existing_session or str(uuid4())
        turn_id = f"claude-{uuid4()}"
        command = [
            executable,
            "--safe-mode",
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(kwargs["output_schema"], ensure_ascii=False),
            "--permission-mode",
            "dontAsk",
            "--tools",
            "WebSearch,WebFetch",
            "--allowedTools",
            "WebSearch,WebFetch",
        ]
        if kwargs.get("model"):
            command.extend(["--model", str(kwargs["model"])])
        if kwargs.get("reasoning_effort"):
            command.extend(["--effort", str(kwargs["reasoning_effort"])])
        if existing_session:
            command.extend(["--resume", existing_session])
        else:
            command.extend(["--session-id", session_id])
        if kwargs.get("on_started"):
            kwargs["on_started"](session_id, turn_id)
        if kwargs.get("on_event"):
            kwargs["on_event"]("agent/cli_started", {"runtime": "claude_code"})
        stdout, stderr, returncode = _run_cancellable_cli(
            command,
            cwd=task_directory,
            timeout_seconds=timeout_seconds,
            cancellation_requested=kwargs.get("cancellation_requested"),
            input_text=_structured_prompt(
                kwargs["prompt"], kwargs["developer_instructions"], kwargs["output_schema"]
            ),
            env=_claude_environment(),
            runtime_name="Claude Code",
        )
        if returncode != 0:
            raise CodexRuntimeUnavailable(sanitize_agent_error(stderr or stdout or "Claude Code failed"))
        try:
            payload = json.loads(stdout)
            if payload.get("is_error"):
                raise CodexRuntimeUnavailable(str(payload.get("result") or "Claude Code failed"))
            final = payload.get("structured_output")
            if not isinstance(final, dict):
                final = _extract_json_object(str(payload.get("result") or ""))
        except (json.JSONDecodeError, AttributeError) as exc:
            raise CodexRuntimeUnavailable("Claude Code returned no valid structured JSON") from exc
        actual_session = str(payload.get("session_id") or session_id)
        usage = dict(payload.get("usage") or {})
        if payload.get("total_cost_usd") is not None:
            usage["total_cost_usd"] = payload["total_cost_usd"]
        return CodexTurnResult(
            actual_session,
            turn_id,
            json.dumps(final, ensure_ascii=False),
            usage,
            [],
        )


class HermesHttpRuntime:
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


class HermesCliRuntime:
    def run_structured(self, **kwargs) -> CodexTurnResult:
        executable = shutil.which("hermes")
        if not executable:
            raise CodexRuntimeUnavailable("Hermes CLI is not installed")
        task_directory = Path(kwargs["task_directory"]).resolve()
        task_directory.mkdir(parents=True, exist_ok=True)
        timeout_seconds = float(kwargs.get("timeout_seconds") or 900)
        prompt = _structured_prompt(
            kwargs["prompt"], kwargs["developer_instructions"], kwargs["output_schema"]
        )
        if len(prompt.encode("utf-8")) > 180_000:
            raise CodexRuntimeUnavailable("Hermes CLI prompt exceeds the safe local command limit")
        command = [
            executable,
            "chat",
            "--quiet",
            "--source",
            "tool",
            "--max-turns",
            "90",
            "-q",
            prompt,
        ]
        if kwargs.get("model"):
            command.extend(["--model", str(kwargs["model"])])
        if kwargs.get("thread_id"):
            command.extend(["--resume", str(kwargs["thread_id"])])
        turn_id = f"hermes-turn-{uuid4()}"
        if kwargs.get("on_event"):
            kwargs["on_event"]("agent/cli_started", {"runtime": "hermes"})
        stdout, stderr, returncode = _run_cancellable_cli(
            command,
            cwd=task_directory,
            timeout_seconds=timeout_seconds,
            cancellation_requested=kwargs.get("cancellation_requested"),
            runtime_name="Hermes",
        )
        combined = "\n".join(value for value in (stdout, stderr) if value)
        session_match = re.search(r"(?im)^\s*session_id:\s*([^\s]+)\s*$", combined)
        session_id = str(
            (session_match.group(1) if session_match else None)
            or kwargs.get("thread_id")
            or f"hermes-session-{uuid4()}"
        )
        if kwargs.get("on_started"):
            kwargs["on_started"](session_id, turn_id)
        if returncode != 0:
            if re.search(r"(?i)(HTTP\s*401|invalid api key|authentication failed)", combined):
                raise CodexRuntimeUnavailable(
                    "Hermes 本机 provider 鉴权失败，请运行 hermes model 或更新 Hermes 私密配置"
                )
            raise CodexRuntimeUnavailable(sanitize_agent_error(stderr or stdout or "Hermes failed"))
        clean_output = re.sub(r"(?im)^\s*session_id:\s*[^\s]+\s*$", "", stdout).strip()
        try:
            final = _extract_json_object(clean_output)
        except json.JSONDecodeError as exc:
            if re.search(r"(?i)(HTTP\s*401|invalid api key|authentication failed)", combined):
                raise CodexRuntimeUnavailable(
                    "Hermes 本机 provider 鉴权失败，请运行 hermes model 或更新 Hermes 私密配置"
                ) from exc
            raise CodexRuntimeUnavailable("Hermes returned no valid structured JSON") from exc
        return CodexTurnResult(
            session_id,
            turn_id,
            json.dumps(final, ensure_ascii=False),
            {},
            [],
        )


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
        allowed_env = (
            "PATH",
            "HOME",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "XDG_CONFIG_HOME",
            "OPENCLAW_CONFIG_PATH",
            "OPENCLAW_STATE_DIR",
        )
        runtime_env = {key: os.environ[key] for key in allowed_env if os.environ.get(key)}
        process = subprocess.Popen(
            command,
            cwd=str(task_directory),
            env=runtime_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
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
        return ClaudeCodeRuntime()
    if runtime_key == "hermes":
        diagnostic = diagnose_hermes()
        return HermesHttpRuntime() if diagnostic.get("transport") == "http_api" else HermesCliRuntime()
    if runtime_key == "openclaw":
        return OpenClawRuntime()
    raise KeyError(runtime_key)
