import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.services.job_queue import run_next_job


MAX_WORKER_CONCURRENCY = 10


def normalize_concurrency(value: int) -> int:
    return min(MAX_WORKER_CONCURRENCY, max(1, value))


def run_once() -> dict:
    with SessionLocal() as db:
        job = run_next_job(db)
        if job is None:
            return {"processed": 0, "job_id": None, "status": "idle"}
        return {
            "processed": 1,
            "job_id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "error_message": job.error_message,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GEO background queue worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Loop sleep interval.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=MAX_WORKER_CONCURRENCY,
        help=f"Maximum jobs processed concurrently (1-{MAX_WORKER_CONCURRENCY}).",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    concurrency = normalize_concurrency(args.concurrency)

    if args.once:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(lambda _index: run_once(), range(concurrency)))
        for result in results:
            print(json.dumps(result, ensure_ascii=False), flush=True)
        return

    # Keep slots independent. The old executor.map() waited for the slowest
    # provider in each wave before claiming another job, so one slow model made
    # every other model appear frozen. A completed slot now replenishes itself
    # immediately while slower calls continue in their own slots.
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(run_once) for _ in range(concurrency)}
        while True:
            done, _pending = wait(futures, return_when=FIRST_COMPLETED)
            processed_any = False
            for future in done:
                futures.remove(future)
                result = future.result()
                if result["processed"]:
                    processed_any = True
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    futures.add(executor.submit(run_once))
            if not processed_any:
                time.sleep(max(args.interval_seconds, 0.1))
                while len(futures) < concurrency:
                    futures.add(executor.submit(run_once))


if __name__ == "__main__":
    main()
