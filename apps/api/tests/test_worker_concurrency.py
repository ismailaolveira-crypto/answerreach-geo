import sys
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


def test_worker_once_can_start_full_observation_matrix_together(monkeypatch, capsys) -> None:
    worker = _worker_module()
    start_barrier = Barrier(125)
    state_lock = Lock()
    started = 0

    def fake_run_once() -> dict:
        nonlocal started
        with state_lock:
            started += 1
            job_id = started
        start_barrier.wait(timeout=10)
        return {"processed": 1, "job_id": job_id, "status": "success"}

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    monkeypatch.setattr(worker.Base.metadata, "create_all", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["run_worker.py", "--once", "--concurrency", "125"])

    worker.main()

    assert started == 125
    assert len(capsys.readouterr().out.strip().splitlines()) == 125
