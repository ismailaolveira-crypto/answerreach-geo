import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier, Lock


def _worker_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_worker.py"
    spec = spec_from_file_location("geo_run_worker", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_concurrency_supports_full_observation_matrix() -> None:
    worker = _worker_module()

    assert worker.DEFAULT_WORKER_CONCURRENCY == 125
    assert worker.MAX_WORKER_CONCURRENCY == 125
    assert worker.normalize_concurrency(-1) == 1
    assert worker.normalize_concurrency(1) == 1
    assert worker.normalize_concurrency(12) == 12
    assert worker.normalize_concurrency(125) == 125
    assert worker.normalize_concurrency(126) == 125
    assert worker.resolve_concurrency(None, once=True) == 1
    assert worker.resolve_concurrency(None, once=False) == 125
    assert worker.resolve_concurrency(8, once=True) == 8


def test_continuous_worker_scales_slots_to_ready_queue_demand() -> None:
    worker = _worker_module()

    assert worker.requested_slot_count(ready_jobs=0, active_slots=0, concurrency=125) == 0
    assert worker.requested_slot_count(ready_jobs=8, active_slots=0, concurrency=125) == 8
    assert worker.requested_slot_count(ready_jobs=200, active_slots=0, concurrency=125) == 125
    assert worker.requested_slot_count(ready_jobs=20, active_slots=120, concurrency=125) == 5
    assert worker.requested_slot_count(ready_jobs=4, active_slots=125, concurrency=125) == 0


def test_worker_once_can_start_full_observation_matrix_together(monkeypatch, capsys) -> None:
    worker = _worker_module()
    start_barrier = Barrier(125)
    state_lock = Lock()
    started = 0

    def fake_run_once(
        _workspace_id: int | None = None,
        _observation_batch_id: int | None = None,
        _worker_id: str | None = None,
    ) -> dict:
        nonlocal started
        with state_lock:
            started += 1
            job_id = started
        start_barrier.wait(timeout=10)
        return {"processed": 1, "job_id": job_id, "status": "success"}

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    worker.run_worker_loop(
        argparse.Namespace(
            once=True,
            workspace_id=None,
            observation_batch_id=None,
            interval_seconds=1,
        ),
        125,
        "test-worker",
    )

    assert started == 125
    assert len(capsys.readouterr().out.strip().splitlines()) == 125


def test_worker_once_passes_workspace_scope(monkeypatch, capsys) -> None:
    worker = _worker_module()
    selected_workspaces: list[int | None] = []

    selected_batches: list[int | None] = []

    def fake_run_once(
        workspace_id: int | None = None,
        observation_batch_id: int | None = None,
        _worker_id: str | None = None,
    ) -> dict:
        selected_workspaces.append(workspace_id)
        selected_batches.append(observation_batch_id)
        return {"processed": 0, "job_id": None, "status": "idle"}

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    worker.run_worker_loop(
        argparse.Namespace(
            once=True,
            workspace_id=1,
            observation_batch_id=85,
            interval_seconds=1,
        ),
        1,
        "test-worker",
    )

    assert selected_workspaces == [1]
    assert selected_batches == [85]
    assert '"status": "idle"' in capsys.readouterr().out


def test_worker_slot_contains_exception_and_accepts_next_call(capsys) -> None:
    worker = _worker_module()
    calls = 0

    def flaky_execute_once() -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("private provider detail must not be logged")
        return {"processed": 0, "job_id": None, "status": "idle"}

    failed = worker.run_worker_slot(flaky_execute_once)
    recovered = worker.run_worker_slot(flaky_execute_once)

    output = capsys.readouterr().out
    assert failed == {
        "processed": 0,
        "job_id": None,
        "status": "slot_error",
        "error_type": "ConnectionError",
    }
    assert recovered["status"] == "idle"
    assert "worker_slot_failed" in output
    assert "private provider detail" not in output
