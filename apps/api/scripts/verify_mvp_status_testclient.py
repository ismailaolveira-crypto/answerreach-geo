import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.db.session import SessionLocal
from app.models import CrawlTask, CrawlTaskLog, LLMProvider, LLMProviderTestRun


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[3] / "outputs" / "latest_mvp_status_testclient_2026-07-06.json"
)


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def verify_mvp_status(
    *,
    project_id: int,
    email: str,
    password: str,
    output_path: Path,
) -> dict[str, Any]:
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(f"/api/projects/{project_id}/mvp-status", headers=headers)
    response.raise_for_status()
    status = response.json()
    checks = status.get("checks") or []
    check_map = {item.get("check"): item for item in checks}
    provider_check = check_map.get("provider.real_collection_ready") or {}
    provider_summary = status.get("provider_summary") or {}
    crawl_health = status.get("crawl_health") or {}
    schedule_status = status.get("schedule_status") or {}
    content_delivery = status.get("content_delivery") or {}

    required_core_checks = [
        "project.detail",
        "crawl.health",
        "maturity_report",
        "stage_goal.completed",
        "stage_goal.timeline",
        "placement.impact.positive",
        "public_delivery_package",
    ]
    missing_core_checks = [name for name in required_core_checks if name not in check_map]
    guidance_missing = [
        item.get("check")
        for item in checks
        if not (item.get("reason") and item.get("next_action_label") and item.get("next_action_type"))
    ]

    _require(status.get("project_id") == project_id, "Project ID mismatch", status)
    _require(not missing_core_checks, "Core MVP checks missing", missing_core_checks)
    _require(not guidance_missing, "MVP checks missing guidance", guidance_missing)
    _require(crawl_health.get("ok") is True, "Crawl health is not OK", crawl_health)
    _require(int(crawl_health.get("total_result_count") or 0) > 0, "No crawl results", crawl_health)
    _require(check_map.get("crawl.schedule_ready"), "Schedule readiness advisory check missing", checks)
    _require(provider_check, "Provider readiness advisory check missing", checks)
    _require(provider_check.get("next_action_url"), "Provider advisory has no next action URL", provider_check)
    initial_real_collection_ready = int(provider_summary.get("real_collection_ready") or 0)

    flip_check = _verify_collection_ready_flip(
        client=client,
        headers=headers,
        project_id=project_id,
        actor_user_id=int(login.json()["user"]["id"]),
        initial_real_collection_ready=initial_real_collection_ready,
    )
    preflight_check = _verify_provider_preflight_block(
        client=client,
        headers=headers,
        project_id=project_id,
    )

    core_ok = all(check_map[name].get("ok") is True for name in required_core_checks)
    result = {
        "ok": core_ok,
        "verification_method": "FastAPI TestClient, no local port binding",
        "project_id": project_id,
        "endpoint": f"/api/projects/{project_id}/mvp-status",
        "mvp_status_ok": status.get("ok"),
        "provider_advisory_ok": provider_check.get("ok") is True,
        "provider_advisory": {
            "status": provider_check.get("status"),
            "reason": provider_check.get("reason"),
            "next_action_type": provider_check.get("next_action_type"),
            "next_action_url": provider_check.get("next_action_url"),
            "provider_summary": {
                "mode": provider_summary.get("mode"),
                "real_ready": int(provider_summary.get("real_ready") or 0),
                "real_collection_ready": int(provider_summary.get("real_collection_ready") or 0),
                "web_search_ready": int(provider_summary.get("web_search_ready") or 0),
                "mock_ready": int(provider_summary.get("mock_ready") or 0),
                "has_real_provider": bool(provider_summary.get("has_real_provider")),
            },
        },
        "provider_collection_ready_flip": flip_check,
        "provider_preflight_block": preflight_check,
        "crawl_health": {
            "status": crawl_health.get("status"),
            "ok": crawl_health.get("ok"),
            "total_tasks": crawl_health.get("total_tasks"),
            "success_tasks": crawl_health.get("success_tasks"),
            "failed_tasks": crawl_health.get("failed_tasks"),
            "latest_task_id": crawl_health.get("latest_task_id"),
            "latest_task_status": crawl_health.get("latest_task_status"),
            "latest_result_count": crawl_health.get("latest_result_count"),
            "total_result_count": crawl_health.get("total_result_count"),
            "next_action_type": crawl_health.get("next_action_type"),
            "next_action_url": crawl_health.get("next_action_url"),
        },
        "schedule_status": {
            "ok": schedule_status.get("ok"),
            "status": schedule_status.get("status"),
            "active_schedule_count": schedule_status.get("active_schedule_count"),
            "hourly_schedule_count": schedule_status.get("hourly_schedule_count"),
            "due_schedule_count": schedule_status.get("due_schedule_count"),
            "latest_schedule_id": schedule_status.get("latest_schedule_id"),
            "latest_schedule_name": schedule_status.get("latest_schedule_name"),
            "latest_schedule_type": schedule_status.get("latest_schedule_type"),
            "latest_interval_hours": schedule_status.get("latest_interval_hours"),
            "latest_next_run_at": schedule_status.get("latest_next_run_at"),
            "next_action_type": schedule_status.get("next_action_type"),
            "next_action_url": schedule_status.get("next_action_url"),
        },
        "content_delivery": {
            "ok": content_delivery.get("ok"),
            "latest_review_score": content_delivery.get("latest_review_score"),
            "latest_review_grade": content_delivery.get("latest_review_grade"),
            "approved_draft_count": content_delivery.get("approved_draft_count"),
            "planned_placement_count": content_delivery.get("planned_placement_count"),
            "published_delivery_count": content_delivery.get("published_delivery_count"),
            "active_share_count": content_delivery.get("active_share_count"),
            "accepted_delivery_count": content_delivery.get("accepted_delivery_count"),
            "next_action_type": content_delivery.get("next_action_type"),
            "next_action_url": content_delivery.get("next_action_url"),
        },
        "checks": [
            [
                item.get("check"),
                item.get("ok"),
                item.get("status"),
                item.get("next_action_type"),
            ]
            for item in checks
        ],
        "limitations": [
            "This snapshot does not verify browser-rendered pages because local port binding may be blocked in the current Codex sandbox.",
            "HTTP-level verify_mvp_demo.py should be rerun after manually starting API and Web services.",
            "provider.real_collection_ready is an advisory launch-readiness check; Mock MVP core checks are evaluated separately.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _verify_collection_ready_flip(
    *,
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
    actor_user_id: int,
    initial_real_collection_ready: int,
) -> dict[str, Any]:
    db = SessionLocal()
    provider: LLMProvider | None = None
    test_run: LLMProviderTestRun | None = None
    try:
        provider = LLMProvider(
            name="Temp collection-ready verification",
            provider_type="openai_compatible",
            model_name="temp-verified-model",
            api_base_url="https://ccdan.cc.cd/v1",
            auth_config={"api_key": "temp-verification-token"},
            status="active",
        )
        db.add(provider)
        db.flush()
        test_run = LLMProviderTestRun(
            provider_id=provider.id,
            actor_user_id=actor_user_id,
            ok=True,
            prompt_text="GEO Provider readiness verification",
            company_name="Temp Company",
            industry="GEO",
            answer_summary="Temporary successful provider test.",
            raw_answer_preview="Temporary successful provider test.",
            latency_ms=1,
        )
        db.add(test_run)
        db.commit()
        response = client.get(f"/api/projects/{project_id}/mvp-status", headers=headers)
        response.raise_for_status()
        status = response.json()
        summary = status.get("provider_summary") or {}
        providers = status.get("providers") or []
        temp_provider = next((item for item in providers if item.get("provider_id") == provider.id), None)
        real_collection_ready = int(summary.get("real_collection_ready") or 0)
        ok = (
            real_collection_ready >= initial_real_collection_ready + 1
            and temp_provider is not None
            and temp_provider.get("collection_ready") is True
            and temp_provider.get("latest_test_ok") is True
        )
        _require(ok, "Provider collection_ready did not flip after a successful test run", status)
        return {
            "ok": True,
            "temp_provider_id": provider.id,
            "initial_real_collection_ready": initial_real_collection_ready,
            "verified_real_collection_ready": real_collection_ready,
            "temp_provider_collection_ready": temp_provider.get("collection_ready") if temp_provider else None,
        }
    finally:
        if test_run is not None:
            db.delete(test_run)
        if provider is not None:
            db.delete(provider)
        db.commit()
        db.close()


def _verify_provider_preflight_block(
    *,
    client: TestClient,
    headers: dict[str, str],
    project_id: int,
) -> dict[str, Any]:
    provider_id: int | None = None
    task_id: int | None = None
    try:
        created = client.post(
            "/api/llm-providers",
            headers=headers,
            json={
                "name": "Temp preflight verification",
                "provider_type": "openai_compatible",
                "model_name": "temp-preflight-model",
                "api_base_url": "https://ccdan.cc.cd/v1",
                "auth_config": {"api_key": "temp-preflight-token"},
                "status": "active",
            },
        )
        created.raise_for_status()
        provider_id = int(created.json()["id"])
        response = client.post(
            f"/api/projects/{project_id}/crawl-tasks",
            headers=headers,
            json={
                "task_type": "manual_batch",
                "schedule_type": "manual",
                "provider_ids": [provider_id],
                "target_question_ids": [],
                "keyword_ids": [],
                "execute_now": True,
            },
        )
        response.raise_for_status()
        task = response.json()
        task_id = int(task["id"])
        error_message = task.get("error_message") or ""
        ok = (
            task.get("status") == "failed"
            and "Provider preflight failed" in error_message
            and "测试记录" in error_message
        )
        _require(ok, "Provider preflight did not block an untested real provider", task)
        return {
            "ok": True,
            "temp_provider_id": provider_id,
            "temp_task_id": task_id,
            "status": task.get("status"),
            "error_message": error_message,
        }
    finally:
        db = SessionLocal()
        try:
            if task_id is not None:
                task = db.get(CrawlTask, task_id)
                if task is not None:
                    logs = list(
                        db.query(CrawlTaskLog)
                        .filter(CrawlTaskLog.task_id == task_id)
                        .all()
                    )
                    for log in logs:
                        db.delete(log)
                    db.delete(task)
            if provider_id is not None:
                provider = db.get(LLMProvider, provider_id)
                if provider is not None:
                    db.delete(provider)
            db.commit()
        finally:
            db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify GEO MVP status API through FastAPI TestClient.")
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    verify_mvp_status(
        project_id=args.project_id,
        email=args.email,
        password=args.password,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
