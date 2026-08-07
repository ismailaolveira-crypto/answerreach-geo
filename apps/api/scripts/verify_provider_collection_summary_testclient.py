import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import LLMProvider


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_provider_collection_summary_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_provider_collection_summary(
    *,
    output_path: Path,
    email: str = "geo-demo-e2e@example.com",
    password: str = "geo-demo-123",
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    summaries: dict[int, dict[str, Any]] = {}
    for provider_id in [9, 10, 12]:
        response = client.get(f"/api/llm-providers/{provider_id}/collection-summary", headers=headers)
        response.raise_for_status()
        summaries[provider_id] = response.json()

    _require(summaries[9]["result_count"] >= 1, "Provider 9 should expose real crawl results", summaries[9])
    _require(summaries[9]["success_task_count"] >= 1, "Provider 9 should expose successful crawl task", summaries[9])
    _require(summaries[12]["result_count"] >= 1, "Provider 12 should expose real crawl results", summaries[12])
    _require(summaries[12]["success_task_count"] >= 1, "Provider 12 should expose successful crawl task", summaries[12])
    _require(summaries[10]["failed_task_count"] >= 1, "Provider 10 should expose timeout/failure evidence", summaries[10])
    _require(
        summaries[10]["latest_task_status"] == "failed",
        "Provider 10 latest task should show failed status",
        summaries[10],
    )
    _require(summaries[9]["collection_ready"] is True, "Provider 9 should be collection ready", summaries[9])
    _require(summaries[12]["collection_ready"] is True, "Provider 12 should be collection ready", summaries[12])

    temp_provider_id: int | None = None
    with SessionLocal() as db:
        try:
            temp_provider = LLMProvider(
                name="Temp Provider Collection Readiness",
                provider_type="openai_compatible",
                model_name="temp-provider-model",
                api_base_url="https://example.invalid/v1",
                auth_config={"api_key": "temp-token"},
                status="active",
            )
            db.add(temp_provider)
            db.commit()
            db.refresh(temp_provider)
            temp_provider_id = temp_provider.id
            temp_response = client.get(f"/api/llm-providers/{temp_provider_id}/collection-summary", headers=headers)
            temp_response.raise_for_status()
            temp_summary = temp_response.json()
            _require(temp_summary["diagnostic_ready"] is True, "Temp provider diagnostic should be ready", temp_summary)
            _require(temp_summary["collection_ready"] is False, "Untested real provider should not be collection ready", temp_summary)
            _require("尚未通过测试调用" in (temp_summary["collection_blocker"] or ""), "Untested provider blocker missing", temp_summary)
        finally:
            if temp_provider_id is not None:
                db.execute(delete(LLMProvider).where(LLMProvider.id == temp_provider_id))
                db.commit()

    result = {
        "ok": True,
        "verification_method": "FastAPI TestClient provider collection summary",
        "provider_summaries": {
            str(provider_id): {
                "result_count": summary["result_count"],
                "success_task_count": summary["success_task_count"],
                "failed_task_count": summary["failed_task_count"],
                "total_tokens": summary["total_tokens"],
                "collection_ready": summary["collection_ready"],
                "collection_blocker": summary["collection_blocker"],
                "diagnostic_ready": summary["diagnostic_ready"],
                "latest_test_ok": summary["latest_test_ok"],
                "latest_task_id": summary["latest_task_id"],
                "latest_task_status": summary["latest_task_status"],
                "latest_task_error_message": summary["latest_task_error_message"],
            }
            for provider_id, summary in summaries.items()
        },
        "untested_provider_preflight": {
            "collection_ready": False,
            "diagnostic_ready": True,
            "blocked_without_test": True,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify provider real collection summary API.")
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_provider_collection_summary(
        email=args.email,
        password=args.password,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
