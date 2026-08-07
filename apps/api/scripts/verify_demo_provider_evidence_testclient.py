import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, engine
from app.main import app


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_demo_provider_evidence_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_demo_provider_evidence(
    *,
    project_id: int,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    latest_response = client.get("/api/projects/mvp-status/latest", headers=headers)
    latest_response.raise_for_status()
    status = latest_response.json()
    _require(status["project_id"] == project_id, "Latest demo project mismatch", status)

    provider_summary = status.get("provider_summary") or {}
    providers = status.get("providers") or []
    _require(provider_summary.get("mode") == "real", "Demo should expose real provider mode", provider_summary)
    _require(int(provider_summary.get("real_collection_ready") or 0) >= 1, "No real collection-ready provider", provider_summary)

    collection_providers = [
        provider
        for provider in providers
        if provider.get("provider_type") != "mock"
        and (
            int(provider.get("project_result_count") or 0) > 0
            or int(provider.get("project_success_task_count") or 0) > 0
            or int(provider.get("project_failed_task_count") or 0) > 0
        )
    ]
    _require(collection_providers, "No project-level provider evidence for demo", providers)

    provider_evidence = {
        int(provider["provider_id"]): {
            "name": provider.get("name"),
            "result_count": int(provider.get("project_result_count") or 0),
            "success_task_count": int(provider.get("project_success_task_count") or 0),
            "failed_task_count": int(provider.get("project_failed_task_count") or 0),
            "total_tokens": int(provider.get("project_total_tokens") or 0),
            "latest_task_id": provider.get("project_latest_task_id"),
            "latest_task_status": provider.get("project_latest_task_status"),
            "latest_task_error_message": provider.get("project_latest_task_error_message"),
        }
        for provider in collection_providers
    }
    if {9, 10, 12} <= set(provider_evidence):
        _require(
            provider_evidence[9]["result_count"] >= 1 and provider_evidence[9]["success_task_count"] >= 1,
            "Provider 9 demo evidence missing",
            provider_evidence[9],
        )
        _require(
            provider_evidence[12]["result_count"] >= 1 and provider_evidence[12]["success_task_count"] >= 1,
            "Provider 12 demo evidence missing",
            provider_evidence[12],
        )
        _require(
            provider_evidence[10]["failed_task_count"] >= 1
            and provider_evidence[10]["latest_task_status"] == "failed",
            "Provider 10 demo failure evidence missing",
            provider_evidence[10],
        )

    result = {
        "ok": True,
        "verification_method": "FastAPI TestClient demo provider evidence contract",
        "demo_route": "/demo",
        "project_id": project_id,
        "provider_mode": provider_summary.get("mode"),
        "real_collection_ready": provider_summary.get("real_collection_ready"),
        "provider_evidence": provider_evidence,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify demo provider evidence data contract.")
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_demo_provider_evidence(
        project_id=args.project_id,
        email=args.email,
        password=args.password,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
