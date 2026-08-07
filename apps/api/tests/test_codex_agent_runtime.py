from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from app.services.codex_agent_runtime import (
    CodexRunTimedOut,
    LocalCodexRuntime,
)


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
