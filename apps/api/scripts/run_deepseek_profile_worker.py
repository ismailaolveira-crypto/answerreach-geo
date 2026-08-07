"""Poll product-created DeepSeek samples and execute them in independent browser profiles."""

import argparse
import os
import socket
import sys
import time
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.v1.deepseek_worker import CollectionError, OpenCliDeepSeekCollector, WorkerApiClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-id", type=int, default=int(os.environ.get("GEO_WORKSPACE_ID", "1")))
    parser.add_argument("--api-base-url", default=os.environ.get("GEO_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--artifact-root", type=Path, default=API_ROOT / "private_artifacts" / "deepseek")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    args = parser.parse_args()
    token = os.environ.get("GEO_WORKER_TOKEN", "").strip()
    if not token:
        raise SystemExit("GEO_WORKER_TOKEN is required")
    worker_id = f"deepseek-profile-worker:{socket.gethostname()}:{os.getpid()}"
    api = WorkerApiClient(args.api_base_url, token, args.workspace_id)
    collector = OpenCliDeepSeekCollector()
    while True:
        try:
            claim = api.claim(worker_id)
        except CollectionError as error:
            if error.code == "api_409":
                if args.once:
                    return
                time.sleep(args.poll_seconds)
                continue
            raise
        try:
            result = collector.collect(claim, args.artifact_root)
            api.complete(claim["sample_id"], claim["lease_token"], result)
        except CollectionError as error:
            api.fail(claim["sample_id"], claim["lease_token"], error)
        except Exception as error:
            api.fail(claim["sample_id"], claim["lease_token"], CollectionError("worker_unexpected", str(error)))
        if args.once:
            return


if __name__ == "__main__":
    main()
