"""Read-only process-specific health check for the global queue Worker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.services.worker_heartbeat import online_global_workers


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a continuous global Worker heartbeat.")
    parser.add_argument(
        "--process-id",
        type=int,
        help="Optionally require the live global Worker to use this exact process id.",
    )
    parser.add_argument("--worker-id", help="Optionally require this exact Worker identity.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        workers = online_global_workers(db, process_id=args.process_id)
        if args.worker_id:
            workers = [worker for worker in workers if worker.worker_id == args.worker_id]

    if not workers:
        if not args.quiet:
            print(
                json.dumps(
                    {
                        "online": False,
                        "process_id": args.process_id,
                        "worker_id": args.worker_id,
                        "reason": "no_live_global_heartbeat",
                    },
                    ensure_ascii=False,
                )
            )
        raise SystemExit(1)

    worker = workers[0]
    if not args.quiet:
        print(
            json.dumps(
                {
                    "online": True,
                    "process_id": worker.process_id,
                    "worker_id": worker.worker_id,
                    "concurrency": worker.concurrency,
                    "last_seen_at": worker.last_seen_at.isoformat(),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
