from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from time import monotonic
from types import SimpleNamespace

import pytest

from app.services.codex_agent_runtime import (
    CodexRuntimeUnavailable,
    CodexRunTimedOut,
    LocalCodexRuntime,
    reset_local_codex_client,
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

    def __init__(self, handle: FakeHandle, turn_kwargs: dict | None = None) -> None:
        self.handle = handle
        self.turn_kwargs = turn_kwargs

    def turn(self, *_args, **kwargs) -> FakeHandle:
        if self.turn_kwargs is not None:
            self.turn_kwargs.update(kwargs)
        return self.handle


@pytest.fixture(autouse=True)
def reset_warm_codex_client():
    reset_local_codex_client()
    yield
    reset_local_codex_client()


def install_fake_codex(
    monkeypatch: pytest.MonkeyPatch,
    handle: FakeHandle,
    turn_kwargs: dict | None = None,
) -> dict[str, int]:
    import openai_codex

    lifecycle = {"created": 0, "closed": 0}

    class FakeCodex:
        def __init__(self) -> None:
            lifecycle["created"] += 1

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def thread_start(self, **_kwargs) -> FakeThread:
            return FakeThread(handle, turn_kwargs)

        def thread_resume(self, *_args, **_kwargs) -> FakeThread:
            return FakeThread(handle, turn_kwargs)

        def close(self) -> None:
            lifecycle["closed"] += 1

    monkeypatch.setattr(openai_codex, "Codex", FakeCodex)
    monkeypatch.setattr(openai_codex, "ApprovalMode", SimpleNamespace(deny_all="deny"))
    monkeypatch.setattr(openai_codex, "Sandbox", SimpleNamespace(workspace_write="workspace"))
    return lifecycle


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


def test_runtime_catalog_exposes_model_specific_reasoning_efforts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openai_codex

    class CatalogCodex:
        metadata = SimpleNamespace(userAgent="Codex Desktop/test")

        def account(self):
            return SimpleNamespace(account=SimpleNamespace(type="chatgpt"))

        def models(self):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        id="gpt-fast",
                        is_default=True,
                        display_name="GPT Fast",
                        description="Fast test model",
                        default_reasoning_effort=SimpleNamespace(value="low"),
                        supported_reasoning_efforts=[
                            SimpleNamespace(reasoning_effort=SimpleNamespace(value="low")),
                            SimpleNamespace(reasoning_effort=SimpleNamespace(value="ultra")),
                        ],
                    )
                ]
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(openai_codex, "Codex", CatalogCodex)
    diagnostic = codex_agent_runtime._probe_local_codex()

    assert diagnostic["default_model"] == "gpt-fast"
    assert diagnostic["default_reasoning_effort"] == "low"
    assert diagnostic["model_options"] == [
        {
            "id": "gpt-fast",
            "display_name": "GPT Fast",
            "description": "Fast test model",
            "default_reasoning_effort": "low",
            "supported_reasoning_efforts": ["low", "ultra"],
        }
    ]


def test_runtime_probe_reports_busy_pool_without_waiting_for_login_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openai_codex

    entered = threading.Event()
    release = threading.Event()

    class BusyCodex:
        metadata = SimpleNamespace(userAgent="Codex Desktop/test")

        def account(self):
            return SimpleNamespace(account=SimpleNamespace(type="chatgpt"))

        def models(self):
            return SimpleNamespace(data=[SimpleNamespace(id="gpt-test", is_default=True)])

        def close(self) -> None:
            return None

    pool = codex_agent_runtime._WarmCodexClientPool(max_size=1)
    monkeypatch.setattr(openai_codex, "Codex", BusyCodex)
    monkeypatch.setattr(codex_agent_runtime, "_warm_codex_client", pool)

    def occupy_pool() -> None:
        with pool.use():
            entered.set()
            assert release.wait(timeout=2)

    worker = threading.Thread(target=occupy_pool)
    worker.start()
    assert entered.wait(timeout=1)
    codex_agent_runtime.invalidate_local_codex_diagnostic_cache()
    started = monotonic()
    try:
        diagnostic = codex_agent_runtime.diagnose_local_codex()
    finally:
        release.set()
        worker.join(timeout=2)

    assert monotonic() - started < 1
    assert diagnostic["ready"] is False
    assert diagnostic["login_status"] == "capacity_busy"
    assert diagnostic["pool_busy"] == 1
    assert codex_agent_runtime.diagnose_local_codex()["ready"] is True


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


@pytest.mark.parametrize("reasoning_effort", ["high", "max", "ultra"])
def test_selected_reasoning_effort_is_forwarded_to_codex_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reasoning_effort: str,
) -> None:
    handle = FakeHandle(complete_immediately=True)
    turn_kwargs: dict = {}
    install_fake_codex(monkeypatch, handle, turn_kwargs)

    LocalCodexRuntime().run_structured(
        task_directory=tmp_path,
        prompt="Return JSON",
        output_schema={"type": "object"},
        developer_instructions="Test only",
        model="gpt-test",
        reasoning_effort=reasoning_effort,
        timeout_seconds=0.1,
    )

    assert turn_kwargs["effort"].value == reasoning_effort


def test_completed_turns_reuse_one_warm_codex_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    handle = FakeHandle(complete_immediately=True)
    lifecycle = install_fake_codex(monkeypatch, handle)

    run_runtime(tmp_path, timeout_seconds=0.1)
    run_runtime(tmp_path, timeout_seconds=0.1)

    assert lifecycle == {"created": 1, "closed": 0}
    snapshot = codex_agent_runtime._warm_codex_client.snapshot()
    assert snapshot["connection_status"] == "warm"
    assert snapshot["connected_since"]
    assert snapshot["reuse_count"] == 2


def test_image_generation_requires_and_copies_a_real_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    skill_path = home / ".codex" / "skills" / ".system" / "imagegen" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# test imagegen skill\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    source = tmp_path / "sdk-output.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nreal-image-payload")

    class ImageHandle:
        id = "turn-image"

        def stream(self):
            yield SimpleNamespace(
                method="item/completed",
                payload=Payload(
                    {
                        "item": {
                            "type": "imageGeneration",
                            "savedPath": str(source),
                            "revisedPrompt": "revised visual prompt",
                        }
                    }
                ),
            )
            yield SimpleNamespace(
                method="turn/completed",
                payload=Payload({"turn": {"status": "completed"}}),
            )

        def interrupt(self) -> None:
            return None

    install_fake_codex(monkeypatch, ImageHandle())
    destination = tmp_path / "task"

    result = LocalCodexRuntime().run_image_generation(
        task_directory=destination,
        prompt="Create one diagram",
        timeout_seconds=0.1,
    )

    assert result.saved_path == destination / "generated-image.png"
    assert result.saved_path.read_bytes() == source.read_bytes()
    assert result.revised_prompt == "revised visual prompt"


def test_two_codex_turns_overlap_on_independent_warm_clients(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import openai_codex

    barrier = threading.Barrier(2)
    lifecycle = {"created": 0, "closed": 0}
    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    class ConcurrentHandle:
        def __init__(self, client_id: int) -> None:
            self.id = f"turn-{client_id}"

        def stream(self):
            nonlocal active, max_active
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                barrier.wait(timeout=1)
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
            finally:
                with counter_lock:
                    active -= 1

        def interrupt(self) -> None:
            return None

    class ConcurrentThread:
        def __init__(self, client_id: int) -> None:
            self.id = f"thread-{client_id}"
            self.handle = ConcurrentHandle(client_id)

        def turn(self, *_args, **_kwargs) -> ConcurrentHandle:
            return self.handle

    class ConcurrentCodex:
        def __init__(self) -> None:
            lifecycle["created"] += 1
            self.client_id = lifecycle["created"]

        def thread_start(self, **_kwargs) -> ConcurrentThread:
            return ConcurrentThread(self.client_id)

        def close(self) -> None:
            lifecycle["closed"] += 1

    monkeypatch.setattr(openai_codex, "Codex", ConcurrentCodex)
    monkeypatch.setattr(openai_codex, "ApprovalMode", SimpleNamespace(deny_all="deny"))
    monkeypatch.setattr(openai_codex, "Sandbox", SimpleNamespace(workspace_write="workspace"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_runtime, tmp_path / f"run-{index}", timeout_seconds=1)
            for index in range(2)
        ]
        results = [future.result(timeout=2) for future in futures]

    assert [result.final_response for result in results] == ['{"ok": true}'] * 2
    assert lifecycle == {"created": 2, "closed": 0}
    assert max_active == 2
    snapshot = codex_agent_runtime._warm_codex_client.snapshot()
    assert snapshot["pool_size"] == 2
    assert snapshot["pool_busy"] == 0
    assert snapshot["pool_limit"] == 10


def test_failed_lease_closes_only_its_client_while_other_lease_keeps_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openai_codex

    lifecycle = {"created": 0, "closed": []}
    barrier = threading.Barrier(2)
    release_healthy = threading.Event()
    client_closed = threading.Event()

    class PoolClient:
        def __init__(self) -> None:
            lifecycle["created"] += 1
            self.client_id = lifecycle["created"]

        def close(self) -> None:
            lifecycle["closed"].append(self.client_id)
            client_closed.set()

    monkeypatch.setattr(openai_codex, "Codex", PoolClient)
    pool = codex_agent_runtime._WarmCodexClientPool(max_size=2)

    def healthy_lease() -> None:
        with pool.use():
            barrier.wait(timeout=1)
            assert release_healthy.wait(timeout=2)

    def failed_lease() -> None:
        with pool.use():
            barrier.wait(timeout=1)
            raise RuntimeError("isolated client failure")

    with ThreadPoolExecutor(max_workers=2) as executor:
        healthy = executor.submit(healthy_lease)
        failed = executor.submit(failed_lease)
        with pytest.raises(RuntimeError, match="isolated client failure"):
            failed.result(timeout=2)

        assert client_closed.wait(timeout=1)
        during_failure = pool.snapshot()
        assert lifecycle["closed"] in ([1], [2])
        assert during_failure["pool_size"] == 1
        assert during_failure["pool_busy"] == 1

        release_healthy.set()
        healthy.result(timeout=2)

    after = pool.snapshot()
    assert after["pool_size"] == 1
    assert after["pool_busy"] == 0
    pool.reset()
    assert sorted(lifecycle["closed"]) == [1, 2]


def test_client_pool_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai_codex

    monkeypatch.setattr(openai_codex, "Codex", lambda: SimpleNamespace(close=lambda: None))
    pool = codex_agent_runtime._WarmCodexClientPool(max_size=1)

    with pool.use():
        with pytest.raises(CodexRuntimeUnavailable, match="capacity remained busy"):
            with pool.use(timeout_seconds=0.01):
                pass

    pool.reset()


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
