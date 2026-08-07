import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import Project
from app.api.routes.projects import _project_operational_readiness
from check_provider_network import DEFAULT_OUTPUT as DEFAULT_NETWORK_OUTPUT
from check_provider_network import check_provider_network


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_yuanquan_operational_readiness.json"


def _summarize_network_check(payload: dict[str, Any], output_path: Path) -> dict[str, Any]:
    results = payload.get("results", [])
    failures = [item for item in results if not item.get("ok")]
    failed_dns = [item for item in failures if item.get("error_stage") == "dns"]
    return {
        "ok": payload.get("ok", False),
        "verification_method": payload.get("verification_method"),
        "checked_provider_count": len(results),
        "ok_count": len(results) - len(failures),
        "failed_count": len(failures),
        "all_failures_are_dns": bool(failures) and len(failed_dns) == len(failures),
        "environment_blocker": bool(results) and len(failed_dns) == len(results),
        "output": str(output_path),
        "safety": payload.get("safety", {}),
        "failures": [
            {
                "provider_id": item.get("provider_id"),
                "name": item.get("name"),
                "host": item.get("host"),
                "error_stage": item.get("error_stage"),
                "error": item.get("error"),
            }
            for item in failures
        ],
    }


def verify_yuanquan_operational_readiness(
    *,
    project_id: int,
    min_ready_platforms: int,
    require_ready: bool,
    output_path: Path,
    include_network_check: bool = False,
    network_output_path: Path = DEFAULT_NETWORK_OUTPUT,
    network_timeout: float = 5.0,
) -> dict[str, Any]:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        readiness = _project_operational_readiness(db, project)

    failed_checks = [item for item in readiness["checks"] if not item["ok"]]
    unready_platforms = [item for item in readiness["platforms"] if not item["ready"]]
    network_check = None
    if include_network_check:
        network_payload = check_provider_network(
            provider_ids=None,
            output_path=network_output_path,
            timeout=network_timeout,
        )
        network_check = _summarize_network_check(network_payload, network_output_path)
    ok = (
        readiness["status"] == "ready"
        and readiness["ready_platform_count"] >= min_ready_platforms
        and not failed_checks
    )
    if not require_ready:
        ok = readiness["status"] in {"ready", "partial"} and readiness["ready_platform_count"] >= 1

    result = {
        "ok": ok,
        "verification_method": "direct operational readiness gate for yuanquan project",
        "project_id": project_id,
        "require_ready": require_ready,
        "min_ready_platforms": min_ready_platforms,
        "status": readiness["status"],
        "summary": readiness["summary"],
        "ok_count": readiness["ok_count"],
        "check_count": readiness["check_count"],
        "ready_platform_count": readiness["ready_platform_count"],
        "required_platform_count": readiness["required_platform_count"],
        "failed_checks": [
            {
                "key": item["key"],
                "label": item["label"],
                "detail": item["detail"],
                "next_action": item.get("next_action"),
            }
            for item in failed_checks
        ],
        "unready_platforms": [
            {
                "key": item["key"],
                "label": item["label"],
                "provider_ids": item["provider_ids"],
                "blockers": item["blockers"],
            }
            for item in unready_platforms
        ],
        "metrics": readiness["metrics"],
        "network_check": network_check,
        "created_at": datetime.now(UTC).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Yuanquan GEO project operational readiness.")
    parser.add_argument("--project-id", type=int, default=1)
    parser.add_argument("--min-ready-platforms", type=int, default=3)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--include-network-check", action="store_true")
    parser.add_argument("--network-output", type=Path, default=DEFAULT_NETWORK_OUTPUT)
    parser.add_argument("--network-timeout", type=float, default=5.0)
    args = parser.parse_args()
    result = verify_yuanquan_operational_readiness(
        project_id=args.project_id,
        min_ready_platforms=args.min_ready_platforms,
        require_ready=not args.allow_partial,
        output_path=args.output,
        include_network_check=args.include_network_check,
        network_output_path=args.network_output,
        network_timeout=args.network_timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
