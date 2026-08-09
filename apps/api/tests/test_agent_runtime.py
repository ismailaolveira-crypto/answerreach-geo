from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.services import agent_runtime


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
    monkeypatch.setattr(agent_runtime.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(agent_runtime.shutil, "which", lambda _name: None)

    claude = agent_runtime.diagnose_claude_agent()
    hermes = agent_runtime.diagnose_hermes()
    openclaw = agent_runtime.diagnose_openclaw()

    assert claude["ready"] is False
    assert claude["login_status"] == "sdk_missing"
    assert hermes["ready"] is False
    assert hermes["login_status"] == "api_key_required"
    assert openclaw["ready"] is False
    assert openclaw["login_status"] == "cli_missing"


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


def test_runtime_factory_maps_each_supported_agent() -> None:
    assert isinstance(agent_runtime.get_agent_runtime("local_codex"), agent_runtime.LocalCodexRuntime)
    assert isinstance(agent_runtime.get_agent_runtime("claude_agent"), agent_runtime.ClaudeAgentRuntime)
    assert isinstance(agent_runtime.get_agent_runtime("hermes"), agent_runtime.HermesRuntime)
    assert isinstance(agent_runtime.get_agent_runtime("openclaw"), agent_runtime.OpenClawRuntime)
