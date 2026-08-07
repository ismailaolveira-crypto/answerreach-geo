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


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_project_dashboard_testclient.json"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _priority_actions(status: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    crawl_health = status.get("crawl_health") or {}
    schedule_status = status.get("schedule_status") or {}
    content_delivery = status.get("content_delivery") or {}
    provider_summary = status.get("provider_summary") or {}
    stage_goal = status.get("stage_goal") or {}
    checks = status.get("checks") or []
    failed_check = next((check for check in checks if not check.get("ok")), None)

    if int(provider_summary.get("real_collection_ready") or 0) == 0:
        actions.append({"key": "provider", "priority": 100})
    if crawl_health.get("status") == "failed" and crawl_health.get("latest_task_id"):
        actions.append({"key": "retry_crawl", "priority": 95})
    if int(schedule_status.get("due_schedule_count") or 0) > 0:
        actions.append({"key": "run_due", "priority": 88})
    if not crawl_health.get("ok"):
        actions.append({"key": "run_crawl", "priority": 82})
    if not status.get("latest_report_url"):
        actions.append({"key": "report", "priority": 78})
    if failed_check and failed_check.get("next_action_type") == "run_full_loop" and stage_goal.get("goal_id"):
        actions.append({"key": "run_full_loop", "priority": 72})
    if int(content_delivery.get("approved_draft_count") or 0) == 0 and status.get("latest_report_url"):
        actions.append({"key": "draft", "priority": 62})
    if int(content_delivery.get("published_delivery_count") or 0) > 0 and int(
        content_delivery.get("active_share_count") or 0
    ) == 0:
        actions.append({"key": "delivery", "priority": 58})
    for check in checks:
        if not check.get("ok") and check.get("next_action_url"):
            actions.append({"key": f"check-{check.get('check')}", "priority": 50})
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in sorted(actions, key=lambda item: item["priority"], reverse=True):
        if action["key"] in seen:
            continue
        seen.add(action["key"])
        deduped.append(action)
    return deduped[:6]


def verify_project_dashboard(
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

    project_response = client.get(f"/api/projects/{project_id}", headers=headers)
    project_response.raise_for_status()
    project = project_response.json()

    status_response = client.get(f"/api/projects/{project_id}/mvp-status", headers=headers)
    status_response.raise_for_status()
    status = status_response.json()

    trends_response = client.get(f"/api/projects/{project_id}/operating-trends?days=14", headers=headers)
    trends_response.raise_for_status()
    trends = trends_response.json()

    goals_response = client.get(f"/api/projects/{project_id}/stage-goals", headers=headers)
    goals_response.raise_for_status()
    goals = goals_response.json()

    reports_response = client.get(f"/api/projects/{project_id}/maturity-reports", headers=headers)
    reports_response.raise_for_status()
    reports = reports_response.json()

    tasks_response = client.get(f"/api/projects/{project_id}/crawl-tasks", headers=headers)
    tasks_response.raise_for_status()
    tasks = tasks_response.json()

    open_alerts_response = client.get(f"/api/alerts?status=open&project_id={project_id}&limit=8", headers=headers)
    open_alerts_response.raise_for_status()
    open_alerts = open_alerts_response.json()

    actions = _priority_actions(status)
    _require(project["id"] == project_id, "Project detail id mismatch", project)
    _require(status["project_id"] == project_id, "MVP status project id mismatch", status)
    _require(isinstance(status.get("checks"), list) and len(status["checks"]) >= 8, "Dashboard checks missing", status)
    _require(status.get("provider_summary", {}).get("mode") in {"real", "mock", "not_ready"}, "Provider mode missing", status)
    _require(len(trends.get("points") or []) == 14, "14-day operating trend should have 14 points", trends)
    _require(
        all({"date", "health_score", "maturity_score", "answer_count"} <= set(point) for point in trends["points"]),
        "Operating trend points missing dashboard fields",
        trends,
    )
    _require(status.get("crawl_health") is not None, "Crawl health missing", status)
    _require(status.get("schedule_status") is not None, "Schedule status missing", status)
    _require(status.get("content_delivery") is not None, "Content delivery missing", status)
    provider_items = status.get("providers") or []
    _require(isinstance(provider_items, list) and len(provider_items) > 0, "Provider items missing", status)
    for provider in provider_items:
        _require("project_result_count" in provider, "Provider project result count missing", provider)
        _require("project_success_task_count" in provider, "Provider project success task count missing", provider)
        _require("project_failed_task_count" in provider, "Provider project failed task count missing", provider)
        _require("project_total_tokens" in provider, "Provider project total tokens missing", provider)
    project_provider_summary = {
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
        for provider in provider_items
    }
    if project_id == 9 and {9, 10, 12} <= set(project_provider_summary):
        _require(
            project_provider_summary[9]["result_count"] >= 1
            and project_provider_summary[9]["success_task_count"] >= 1,
            "Provider 9 project collection evidence missing",
            project_provider_summary[9],
        )
        _require(
            project_provider_summary[12]["result_count"] >= 1
            and project_provider_summary[12]["success_task_count"] >= 1,
            "Provider 12 project collection evidence missing",
            project_provider_summary[12],
        )
        _require(
            project_provider_summary[10]["failed_task_count"] >= 1
            and project_provider_summary[10]["latest_task_status"] == "failed",
            "Provider 10 project failure evidence missing",
            project_provider_summary[10],
        )
    _require(isinstance(goals, list), "Stage goals response should be a list", goals)
    _require(isinstance(reports, list), "Maturity reports response should be a list", reports)
    _require(isinstance(tasks, list), "Crawl tasks response should be a list", tasks)
    _require(isinstance(open_alerts, list), "Project alerts response should be a list", open_alerts)

    result = {
        "ok": True,
        "verification_method": "FastAPI TestClient project dashboard data contract",
        "project_id": project_id,
        "dashboard_route": f"/projects/{project_id}/dashboard",
        "project_name": project["name"],
        "mvp_status_ok": status["ok"],
        "provider_mode": status.get("provider_summary", {}).get("mode"),
        "real_collection_ready": status.get("provider_summary", {}).get("real_collection_ready"),
        "check_count": len(status["checks"]),
        "passed_check_count": sum(1 for check in status["checks"] if check.get("ok")),
        "trend_point_count": len(trends["points"]),
        "stage_goal_count": len(goals),
        "report_count": len(reports),
        "crawl_task_count": len(tasks),
        "open_alert_count": len(open_alerts),
        "priority_action_keys": [item["key"] for item in actions],
        "project_provider_summary": project_provider_summary,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify project dashboard data contract.")
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_project_dashboard(
        project_id=args.project_id,
        email=args.email,
        password=args.password,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
