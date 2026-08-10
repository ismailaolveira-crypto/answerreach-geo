import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
import secrets
import signal
import socket
import sys
from threading import Event, Thread
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import SessionLocal
from app.services.job_queue import count_ready_jobs, recover_orphaned_jobs, run_next_job
from app.services.worker_heartbeat import (
    WORKER_HEARTBEAT_INTERVAL_SECONDS,
    register_worker,
    stop_worker,
    touch_worker,
)


DEFAULT_WORKER_CONCURRENCY = 125
MAX_WORKER_CONCURRENCY = 125


def normalize_concurrency(value: int) -> int:
    return min(MAX_WORKER_CONCURRENCY, max(1, value))


def resolve_concurrency(requested: int | None, *, once: bool) -> int:
    """Keep one-shot diagnostics bounded unless concurrency is explicit."""

    if requested is None:
        return 1 if once else DEFAULT_WORKER_CONCURRENCY
    return normalize_concurrency(requested)


def run_once(
    workspace_id: int | None = None,
    observation_batch_id: int | None = None,
    worker_id: str | None = None,
) -> dict:
    with SessionLocal() as db:
        job = run_next_job(
            db,
            workspace_id=workspace_id,
            observation_batch_id=observation_batch_id,
            worker_id=worker_id,
        )
        if job is None:
            return {"processed": 0, "job_id": None, "status": "idle"}
        return {
            "processed": 1,
            "job_id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "error_message": job.error_message,
        }


def worker_heartbeat_loop(stop_event: Event, worker_id: str) -> None:
    while not stop_event.wait(WORKER_HEARTBEAT_INTERVAL_SECONDS):
        try:
            with SessionLocal() as db:
                touch_worker(db, worker_id)
        except Exception as exc:  # keep paid work alive if monitoring briefly fails
            print(
                json.dumps(
                    {
                        "event": "worker_heartbeat_failed",
                        "error_type": type(exc).__name__,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


def run_worker_slot(execute_once) -> dict:
    """Contain infrastructure failures to one slot without killing the Worker.

    Provider failures are already persisted by ``run_job``. This boundary is
    for failures outside that handler (for example a brief database disconnect
    while claiming work). Error text is intentionally omitted because upstream
    exceptions can contain private request details.
    """

    try:
        return execute_once()
    except Exception as exc:
        result = {
            "processed": 0,
            "job_id": None,
            "status": "slot_error",
            "error_type": type(exc).__name__,
        }
        print(
            json.dumps({"event": "worker_slot_failed", **result}, ensure_ascii=False),
            flush=True,
        )
        return result


def requested_slot_count(*, ready_jobs: int, active_slots: int, concurrency: int) -> int:
    """Return only the additional slots required by current queue demand."""

    available_slots = max(0, concurrency - active_slots)
    return min(max(0, ready_jobs), available_slots)


def run_worker_loop(args: argparse.Namespace, concurrency: int, worker_id: str) -> None:
    def execute_once() -> dict:
        return run_once(
            args.workspace_id,
            args.observation_batch_id,
            worker_id,
        )

    if args.once:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(
                executor.map(
                    lambda _index: run_worker_slot(execute_once),
                    range(concurrency),
                )
            )
        for result in results:
            print(json.dumps(result, ensure_ascii=False), flush=True)
        return

    # Keep provider calls independent, but grow the executor to actual queue
    # demand. Starting all 125 slots while idle made every slot poll SQLite,
    # starving ordinary page/API reads even though there was no work to do.
    # Demand-aware refill preserves the 125-job ceiling without idle DB churn.
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = set()
        while True:
            try:
                with SessionLocal() as db:
                    ready_jobs = count_ready_jobs(
                        db,
                        workspace_id=args.workspace_id,
                        observation_batch_id=args.observation_batch_id,
                    )
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "event": "worker_queue_probe_failed",
                            "error_type": type(exc).__name__,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                time.sleep(max(args.interval_seconds, 0.1))
                continue

            for _ in range(
                requested_slot_count(
                    ready_jobs=ready_jobs,
                    active_slots=len(futures),
                    concurrency=concurrency,
                )
            ):
                futures.add(executor.submit(run_worker_slot, execute_once))

            if not futures:
                time.sleep(max(args.interval_seconds, 0.1))
                continue

            done, _pending = wait(
                futures,
                timeout=max(args.interval_seconds, 0.1),
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                futures.remove(future)
                result = future.result()
                if result["processed"]:
                    print(json.dumps(result, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GEO background queue worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument(
        "--workspace-id",
        type=int,
        default=None,
        help="Only claim jobs for one workspace. Intended for bounded diagnostics and recovery.",
    )
    parser.add_argument(
        "--observation-batch-id",
        type=int,
        default=None,
        help="Only claim observation jobs from one ledger batch.",
    )
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Loop sleep interval.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=(
            "Maximum jobs processed concurrently. Defaults to 1 with --once "
            f"and {DEFAULT_WORKER_CONCURRENCY} in continuous mode "
            f"(allowed 1-{MAX_WORKER_CONCURRENCY})."
        ),
    )
    parser.add_argument(
        "--worker-id",
        help="Stable Worker identity used by container-specific health checks.",
    )
    args = parser.parse_args()

    concurrency = resolve_concurrency(args.concurrency, once=args.once)
    worker_id = args.worker_id or (
        f"queue:{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
    )
    with SessionLocal() as db:
        if not args.once:
            recovery = recover_orphaned_jobs(db, workspace_id=args.workspace_id)
            if recovery["recovered"] or recovery["failed"]:
                print(
                    json.dumps({"event": "worker_recovery", **recovery}, ensure_ascii=False),
                    flush=True,
                )
        register_worker(
            db,
            worker_id=worker_id,
            mode="once" if args.once else "continuous",
            hostname=socket.gethostname(),
            process_id=os.getpid(),
            concurrency=concurrency,
            workspace_id=args.workspace_id,
            observation_batch_id=args.observation_batch_id,
        )
    heartbeat_stop = Event()
    heartbeat_thread = Thread(
        target=worker_heartbeat_loop,
        args=(heartbeat_stop, worker_id),
        name="queue-worker-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def request_graceful_stop(_signum, _frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_graceful_stop)
    try:
        run_worker_loop(args, concurrency, worker_id)
    except KeyboardInterrupt:
        print(
            json.dumps({"event": "worker_stopping", "reason": "operator_interrupt"}),
            flush=True,
        )
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)
        try:
            with SessionLocal() as db:
                stop_worker(db, worker_id)
        except Exception as exc:
            print(
                json.dumps(
                    {"event": "worker_stop_heartbeat_failed", "error_type": type(exc).__name__},
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
