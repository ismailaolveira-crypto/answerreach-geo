from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _worker_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_worker.py"
    spec = spec_from_file_location("geo_run_worker", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_concurrency_defaults_and_clamps_to_ten() -> None:
    worker = _worker_module()

    assert worker.MAX_WORKER_CONCURRENCY == 10
    assert worker.normalize_concurrency(-1) == 1
    assert worker.normalize_concurrency(1) == 1
    assert worker.normalize_concurrency(10) == 10
    assert worker.normalize_concurrency(11) == 10
