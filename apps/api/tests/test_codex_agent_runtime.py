from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from app.services.codex_agent_runtime import (
    CodexRunTimedOut,
    LocalCodexRuntime,
)
from app.services import codex_agent_runtime
from app.v1.agent_orchestration import _validate_verified_brand_claims


class Payload:
    def __init__(self, value: dict) -> None:
        self.value = value

    def model_dump(self, **_kwargs) -> dict:
        return self.value


class FakeHandle:
    id = "turn-test"

    def __init__(self, *, complete_immediately: bool = False) -> None:
        self.complete_immediately = complete_immediately
        self.interrupted = threading.Event()
        self.interrupt_calls = 0

    def stream(self):
        yield SimpleNamespace(method="turn/started", payload=Payload({"turn": {"status": "inProgress"}}))
        if self.complete_immediately:
            yield SimpleNamespace(
                method="item/completed",
                payload=Payload(
                    {
                        "item": {
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": '{"ok": true}',
                        }
                    }
                ),
            )
            yield SimpleNamespace(
                method="turn/completed",
                payload=Payload({"turn": {"status": "completed"}}),
            )
            return
        assert self.interrupted.wait(timeout=1)
        raise RuntimeError("stream interrupted")

    def interrupt(self) -> None:
        self.interrupt_calls += 1
        self.interrupted.set()


class FakeThread:
    id = "thread-test"

    def __init__(self, handle: FakeHandle) -> None:
        self.handle = handle

    def turn(self, *_args, **_kwargs) -> FakeHandle:
        return self.handle


def install_fake_codex(monkeypatch: pytest.MonkeyPatch, handle: FakeHandle) -> None:
    import openai_codex

    class FakeCodex:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def thread_start(self, **_kwargs) -> FakeThread:
            return FakeThread(handle)

        def thread_resume(self, *_args, **_kwargs) -> FakeThread:
            return FakeThread(handle)

    monkeypatch.setattr(openai_codex, "Codex", FakeCodex)
    monkeypatch.setattr(openai_codex, "ApprovalMode", SimpleNamespace(deny_all="deny"))
    monkeypatch.setattr(openai_codex, "Sandbox", SimpleNamespace(workspace_write="workspace"))


def run_runtime(tmp_path: Path, *, timeout_seconds: float) -> object:
    return LocalCodexRuntime().run_structured(
        task_directory=tmp_path,
        prompt="Return JSON",
        output_schema={"type": "object"},
        developer_instructions="Test only",
        timeout_seconds=timeout_seconds,
    )


def test_diagnostic_cache_reuses_snapshot_until_invalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_probe() -> dict:
        nonlocal calls
        calls += 1
        return {"ready": True, "probe": calls}

    codex_agent_runtime.invalidate_local_codex_diagnostic_cache()
    monkeypatch.setattr(codex_agent_runtime, "_probe_local_codex", fake_probe)
    try:
        first = codex_agent_runtime.diagnose_local_codex()
        second = codex_agent_runtime.diagnose_local_codex()
        assert first == second == {"ready": True, "probe": 1}
        assert calls == 1

        codex_agent_runtime.invalidate_local_codex_diagnostic_cache()
        refreshed = codex_agent_runtime.diagnose_local_codex()
        assert refreshed == {"ready": True, "probe": 2}
        assert calls == 2
    finally:
        codex_agent_runtime.invalidate_local_codex_diagnostic_cache()


def test_timeout_interrupts_the_real_turn_handle_and_surfaces_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    handle = FakeHandle()
    install_fake_codex(monkeypatch, handle)

    with pytest.raises(CodexRunTimedOut, match="exceeded"):
        run_runtime(tmp_path, timeout_seconds=0.02)

    assert handle.interrupt_calls == 1


def test_completed_turn_disarms_timeout_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    handle = FakeHandle(complete_immediately=True)
    install_fake_codex(monkeypatch, handle)

    result = run_runtime(tmp_path, timeout_seconds=0.1)

    assert result.final_response == '{"ok": true}'
    assert result.thread_id == "thread-test"
    assert handle.interrupt_calls == 0


def test_verified_brand_claims_must_copy_stored_statement_exactly() -> None:
    fact = SimpleNamespace(
        statement="企业 AI 系统的统一 Token 管理与模型调度平台",
        source_url="https://brand.example/",
    )
    rewritten = {
        "master": {
            "claims": [
                {
                    "text": "某品牌是企业 AI Token 管理和调度平台。",
                    "source_url": "https://brand.example/?from=agent",
                    "verification_status": "source_linked",
                }
            ]
        }
    }

    with pytest.raises(ValueError, match="rewrote verified brand facts"):
        _validate_verified_brand_claims(rewritten, [fact])

    exact = {
        "master": {
            "claims": [
                {
                    "text": fact.statement,
                    "source_url": "https://brand.example",
                    "verification_status": "source_linked",
                }
            ]
        }
    }
    _validate_verified_brand_claims(exact, [fact])
