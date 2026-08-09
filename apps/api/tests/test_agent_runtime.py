from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.services import agent_runtime
from app.services.codex_agent_runtime import CodexRunInterrupted, CodexRuntimeUnavailable
from app.v1.schemas import AgentRuntimeRead


def _settings(**overrides):
    values = {
        "anthropic_api_key": None,
        "claude_agent_models": "claude-sonnet-4-6,claude-opus-4-6",
        "hermes_api_url": "http://127.0.0.1:8642",
        "hermes_api_key": None,
        "openclaw_agent_id": "main",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_catalog_keeps_unconfigured_runtimes_honest(monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: _settings())
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda _name: None)

    claude = agent_runtime.diagnose_claude_agent()
    hermes = agent_runtime.diagnose_hermes()
    openclaw = agent_runtime.diagnose_openclaw()

    assert claude["ready"] is False
    assert claude["login_status"] == "cli_missing"
    assert hermes["ready"] is False
    assert hermes["login_status"] == "cli_missing"
    assert openclaw["ready"] is False
    assert openclaw["login_status"] == "cli_missing"


def test_claude_diagnostic_reuses_local_cli_login(monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: _settings())
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(agent_runtime, "_run_json_command", lambda *_args, **_kwargs: {"loggedIn": True})
    monkeypatch.setattr(agent_runtime, "_run_text_command", lambda *_args, **_kwargs: "2.1.210 (Claude Code)\n")

    diagnostic = agent_runtime.diagnose_claude_agent()

    assert diagnostic["ready"] is True
    assert diagnostic["display_name"] == "Claude Code"
    assert diagnostic["login_status"] == "local_cli_authenticated"
    assert diagnostic["transport"] == "official_cli"


def test_hermes_diagnostic_uses_local_profile_without_duplicate_key(monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: _settings())
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda name: "/bin/hermes" if name == "hermes" else None)

    def command_output(command, **_kwargs):
        if "status" in command:
            return "  Model: deepseek-v4-flash\n  Provider: DeepSeek\n"
        if "--version" in command:
            return "Hermes Agent v0.18.2\n"
        return ""

    monkeypatch.setattr(agent_runtime, "_run_text_command", command_output)

    diagnostic = agent_runtime.diagnose_hermes()

    assert diagnostic["ready"] is True
    assert diagnostic["connection_status"] == "configured"
    assert diagnostic["default_model"] == "deepseek-v4-flash"
    assert diagnostic["model_options"][0]["supported_reasoning_efforts"] == []
    assert AgentRuntimeRead.model_validate(diagnostic).connection_status == "configured"


def test_claude_cli_adapter_reads_structured_output(monkeypatch, tmp_path: Path) -> None:
    observed: dict = {}
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: _settings())
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)

    def run_cli(command, **kwargs):
        observed["command"] = command
        observed["input"] = kwargs["input_text"]
        return (
            json.dumps(
                {
                    "is_error": False,
                    "session_id": "12345678-1234-1234-1234-123456789abc",
                    "structured_output": {"ok": True},
                    "usage": {"input_tokens": 10},
                }
            ),
            "",
            0,
        )

    monkeypatch.setattr(agent_runtime, "_run_cancellable_cli", run_cli)
    result = agent_runtime.ClaudeCodeRuntime().run_structured(
        task_directory=tmp_path,
        prompt="Return ok",
        output_schema={"type": "object"},
        developer_instructions="Return JSON",
        model="claude-sonnet-4-6",
        reasoning_effort="low",
    )

    assert json.loads(result.final_response) == {"ok": True}
    assert "--output-format" in observed["command"]
    assert "--json-schema" in observed["command"]
    assert "SYSTEM CONTRACT" in observed["input"]


def test_hermes_cli_adapter_reads_json_and_session(monkeypatch, tmp_path: Path) -> None:
    observed: dict = {}
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda name: "/bin/hermes" if name == "hermes" else None)

    def run_cli(command, **_kwargs):
        observed["command"] = command
        return ('{"ok":true}\nsession_id: hermes-session-1\n', "", 0)

    monkeypatch.setattr(agent_runtime, "_run_cancellable_cli", run_cli)
    result = agent_runtime.HermesCliRuntime().run_structured(
        task_directory=tmp_path,
        prompt="Return ok",
        output_schema={"type": "object"},
        developer_instructions="Return JSON",
        model="deepseek-v4-flash",
        reasoning_effort=None,
    )

    assert json.loads(result.final_response) == {"ok": True}
    assert result.thread_id == "hermes-session-1"
    assert observed["command"][:3] == ["/bin/hermes", "chat", "--quiet"]


def test_hermes_cli_adapter_reports_provider_auth_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda name: "/bin/hermes" if name == "hermes" else None)
    monkeypatch.setattr(
        agent_runtime,
        "_run_cancellable_cli",
        lambda *_args, **_kwargs: ("session_id: failed-session\n", "HTTP 401: Invalid API key", 1),
    )

    with pytest.raises(CodexRuntimeUnavailable, match="provider 鉴权失败"):
        agent_runtime.HermesCliRuntime().run_structured(
            task_directory=tmp_path,
            prompt="Return ok",
            output_schema={"type": "object"},
            developer_instructions="Return JSON",
            model="deepseek-v4-flash",
            reasoning_effort=None,
        )


def test_cli_helper_interrupts_only_its_own_process(monkeypatch, tmp_path: Path) -> None:
    class Process:
        stdin = None
        returncode = None
        terminated = False

        def communicate(self, timeout=None):
            if not self.terminated:
                raise subprocess.TimeoutExpired("agent", timeout or 0)
            self.returncode = -15
            return "", ""

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    process = Process()
    monkeypatch.setattr(agent_runtime.subprocess, "Popen", lambda *_args, **_kwargs: process)

    with pytest.raises(CodexRunInterrupted):
        agent_runtime._run_cancellable_cli(
            ["agent"],
            cwd=tmp_path,
            timeout_seconds=10,
            cancellation_requested=lambda: True,
            runtime_name="Test Agent",
        )

    assert process.terminated is True


def test_openclaw_adapter_uses_official_json_envelope(monkeypatch, tmp_path: Path) -> None:
    class Process:
        returncode = 0

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return (
                json.dumps(
                    {
                        "ok": True,
                        "final": json.dumps({"ok": True}),
                        "usage": {"total": 10},
                        "sessionId": "openclaw-session-1",
                    }
                ),
                "",
            )

    commands: list[list[str]] = []
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: _settings())
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda _name: "/usr/local/bin/openclaw")
    monkeypatch.setattr(
        agent_runtime.subprocess,
        "Popen",
        lambda command, **_kwargs: commands.append(command) or Process(),
    )

    result = agent_runtime.OpenClawRuntime().run_structured(
        task_directory=tmp_path,
        prompt="Return ok",
        output_schema={"type": "object"},
        developer_instructions="Return JSON",
        model="openai/gpt-test",
        reasoning_effort="low",
    )

    assert json.loads(result.final_response) == {"ok": True}
    assert result.thread_id == "openclaw-session-1"
    assert commands[0][:3] == ["/usr/local/bin/openclaw", "agent", "--agent"]
    assert "--json" in commands[0]


def test_runtime_factory_maps_each_supported_agent(monkeypatch) -> None:
    monkeypatch.setattr(agent_runtime, "diagnose_hermes", lambda: {"transport": "official_cli"})
    assert isinstance(agent_runtime.get_agent_runtime("local_codex"), agent_runtime.LocalCodexRuntime)
    assert isinstance(agent_runtime.get_agent_runtime("claude_agent"), agent_runtime.ClaudeCodeRuntime)
    assert isinstance(agent_runtime.get_agent_runtime("hermes"), agent_runtime.HermesCliRuntime)
    assert isinstance(agent_runtime.get_agent_runtime("openclaw"), agent_runtime.OpenClawRuntime)
