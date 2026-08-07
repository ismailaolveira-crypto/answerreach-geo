import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_e2e_demo import DEFAULT_OUTPUT_PATH, run_demo


DEFAULT_VERIFY_OUTPUT = (
    Path(__file__).resolve().parents[3] / "outputs" / "latest_mvp_verification.json"
)


class VerificationError(AssertionError):
    pass


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise VerificationError(f"{message}: {detail!r}")


def _load_summary(path: Path) -> dict[str, Any]:
    _require(path.exists(), "Demo summary file does not exist", str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _get_json(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> Any:
    response = _request_with_retry(client, "GET", url, headers=headers)
    response.raise_for_status()
    return response.json()


def _get_text(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    response = _request_with_retry(client, "GET", url, headers=headers)
    response.raise_for_status()
    return response.text


def _request_with_retry(client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    last_response: httpx.Response | None = None
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = client.request(method, url, **kwargs)
            last_response = response
            if response.status_code < 500:
                return response
        except httpx.HTTPError as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(0.4 * (attempt + 1))
    if last_response is not None:
        return last_response
    assert last_error is not None
    raise last_error


def _login(client: httpx.Client, api_base_url: str, email: str, password: str) -> str:
    response = _request_with_retry(
        client,
        "POST",
        f"{api_base_url}/api/auth/login",
        json={"email": email, "password": password},
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token")
    _require(isinstance(token, str) and token, "Login did not return access token", data)
    return token


def _assert_contains(name: str, body: str, markers: list[str]) -> list[dict[str, Any]]:
    checks = []
    for marker in markers:
        found = marker in body
        checks.append({"name": name, "marker": marker, "ok": found})
        _require(found, f"Page marker missing in {name}", marker)
    return checks


def verify_demo(
    *,
    summary_path: Path,
    output_path: Path,
    api_base_url: str,
    web_base_url: str,
    refresh_demo: bool = False,
    reset_demo: bool = False,
) -> dict[str, Any]:
    if refresh_demo:
        run_demo(output_path=summary_path, reset=reset_demo)

    summary = _load_summary(summary_path)
    project_id = int(summary["project_id"])
    report_id = int(summary["report_ids"][-1])
    placement_id = int(summary["stage_goal"]["placement_id"])
    goal_id = int(summary["stage_goal"]["goal_id"])
    share_token = str(summary["stage_goal"]["share_token"])
    login = summary["login"]

    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=30, follow_redirects=True, trust_env=False) as client:
        token = _login(client, api_base_url, str(login["email"]), str(login["password"]))
        headers = {"Authorization": f"Bearer {token}"}
        page_headers = {"Cookie": f"geo_session={token}"}

        me = _get_json(client, f"{api_base_url}/api/auth/me", headers=headers)
        results.append({"check": "auth.me", "ok": me["email"] == login["email"]})
        _require(me["email"] == login["email"], "Auth user mismatch", me)

        project = _get_json(client, f"{api_base_url}/api/projects/{project_id}", headers=headers)
        results.append({"check": "project.detail", "ok": project["id"] == project_id})
        _require(project["id"] == project_id, "Project ID mismatch", project)

        mvp_status = _get_json(
            client,
            f"{api_base_url}/api/projects/{project_id}/mvp-status",
            headers=headers,
        )
        mvp_checks = mvp_status.get("checks") or []
        crawl_health = mvp_status.get("crawl_health") or {}
        mvp_check_names = {item.get("check") for item in mvp_checks}
        provider_summary = mvp_status.get("provider_summary") or {}
        provider_check = next(
            (item for item in mvp_checks if item.get("check") == "provider.real_collection_ready"),
            None,
        )
        mvp_checks_have_guidance = all(
            item.get("reason") and item.get("next_action_label") and item.get("next_action_type")
            for item in mvp_checks
        )
        mvp_status_ok = (
            mvp_status.get("ok") is True
            and mvp_status.get("project_id") == project_id
            and len(mvp_checks) >= 7
            and "crawl.health" in mvp_check_names
            and crawl_health.get("ok") is True
            and int(crawl_health.get("total_result_count") or 0) > 0
            and (mvp_status.get("stage_goal") or {}).get("placement_id") == placement_id
            and mvp_checks_have_guidance
        )
        results.append(
            {
                "check": "project.mvp_status",
                "ok": mvp_status_ok,
                "status_check_count": len(mvp_checks),
                "api_ok": mvp_status.get("ok"),
                "has_guidance": mvp_checks_have_guidance,
                "crawl_health": crawl_health,
            }
        )
        _require(mvp_status_ok, "Project MVP status API did not verify the full loop", mvp_status)
        results.append(
            {
                "check": "provider.real_collection_ready",
                "ok": bool(provider_check and provider_check.get("ok") is True),
                "advisory": True,
                "status": provider_check.get("status") if provider_check else "missing",
                "reason": provider_check.get("reason") if provider_check else "Provider readiness check missing",
                "next_action_type": provider_check.get("next_action_type") if provider_check else "open_provider_config",
                "next_action_url": provider_check.get("next_action_url") if provider_check else "/admin/providers",
                "provider_summary": {
                    "real_collection_ready": int(provider_summary.get("real_collection_ready") or 0),
                    "web_search_ready": int(provider_summary.get("web_search_ready") or 0),
                    "mock_ready": int(provider_summary.get("mock_ready") or 0),
                    "mode": provider_summary.get("mode"),
                },
            }
        )

        report = _get_json(
            client,
            f"{api_base_url}/api/projects/{project_id}/maturity-reports/{report_id}",
            headers=headers,
        )
        results.append(
            {
                "check": "maturity_report",
                "ok": report["total_score"] >= 60,
                "total_score": report["total_score"],
                "maturity_level": report["maturity_level"],
            }
        )
        _require(report["total_score"] >= 60, "Maturity report score too low", report)

        goals = _get_json(
            client,
            f"{api_base_url}/api/projects/{project_id}/stage-goals",
            headers=headers,
        )
        goal = next((item for item in goals if int(item["id"]) == goal_id), None)
        results.append({"check": "stage_goal.completed", "ok": goal is not None and goal["status"] == "completed"})
        _require(goal is not None and goal["status"] == "completed", "Stage goal not completed", goal)

        timeline = _get_json(
            client,
            f"{api_base_url}/api/projects/{project_id}/stage-goals/{goal_id}/timeline",
            headers=headers,
        )
        event_types = {item["event_type"] for item in timeline}
        required_events = {
            "stage_goal.action.run_crawl",
            "stage_goal.action.generate_draft_and_review",
            "stage_goal.action.approve_and_create_placement",
            "stage_goal.action.publish_prepare_delivery",
            "stage_goal.delivery_confirmed",
            "delivery.confirmed",
        }
        results.append(
            {
                "check": "stage_goal.timeline",
                "ok": required_events.issubset(event_types),
                "event_count": len(timeline),
            }
        )
        _require(required_events.issubset(event_types), "Timeline events missing", sorted(required_events - event_types))

        impact = _get_json(
            client,
            f"{api_base_url}/api/projects/{project_id}/placements/{placement_id}/impact",
            headers=headers,
        )
        review_report = impact["review_report"]
        metric_deltas = review_report["metric_deltas"]
        impact_ok = (
            review_report["status"] == "positive"
            and metric_deltas["company_mention_rate_delta"] > 0
            and metric_deltas["company_recommendation_rate_delta"] > 0
            and metric_deltas["source_after_appearances"] > 0
        )
        results.append(
            {
                "check": "placement.impact.positive",
                "ok": impact_ok,
                "status": review_report["status"],
                "metric_deltas": metric_deltas,
            }
        )
        _require(impact_ok, "Placement impact is not positive", review_report)

        public_package = _get_json(
            client,
            f"{api_base_url}/api/public/delivery-packages/{share_token}",
        )
        deliverables = public_package.get("deliverables") or []
        results.append(
            {
                "check": "public_delivery_package",
                "ok": len(deliverables) >= 1,
                "deliverable_count": len(deliverables),
            }
        )
        _require(len(deliverables) >= 1, "Public delivery package has no deliverables", public_package)

        pages = [
            (
                "demo",
                f"{web_base_url}/demo",
                [
                    "GEO MVP 闭环演示",
                    "正向效果",
                    "+50%",
                    "目标信源出现",
                    "20",
                    "真实检索接入",
                    str(login["email"]),
                ],
            ),
            (
                "project",
                f"{web_base_url}/projects/{project_id}",
                ["GEO 闭环演示项目", "复盘时间线", "客户确认交付报告", "completed"],
            ),
            (
                "report",
                f"{web_base_url}/projects/{project_id}/reports/{report_id}",
                ["GEO 成熟度优化报告", "样本可信度", "模型覆盖"],
            ),
            (
                "impact",
                f"{web_base_url}/projects/{project_id}/placements/{placement_id}/impact",
                ["复盘报告", "正向效果", "20"],
            ),
            (
                "delivery_package",
                f"{web_base_url}/projects/{project_id}/delivery-package",
                ["客户交付包", "确认阅读", "演示客户", "已确认"],
            ),
        ]
        page_checks: list[dict[str, Any]] = []
        for name, url, markers in pages:
            response = _request_with_retry(client, "GET", url, headers=page_headers)
            response.raise_for_status()
            body = response.text
            page_checks.extend(_assert_contains(name, body, markers))
        public_body = _get_text(client, f"{web_base_url}/share/delivery/{share_token}")
        page_checks.extend(
            _assert_contains(
                "public_share",
                public_body,
                ["GEO 交付报告", "阶段目标投放", "已确认"],
            )
        )
        results.append({"check": "frontend_pages", "ok": True, "marker_count": len(page_checks)})

    ok = all(item.get("ok") is True for item in results if item.get("advisory") is not True)
    verification = {
        "ok": ok,
        "summary_path": str(summary_path),
        "api_base_url": api_base_url,
        "web_base_url": web_base_url,
        "project_id": project_id,
        "report_id": report_id,
        "placement_id": placement_id,
        "goal_id": goal_id,
        "public_share_url": summary["public_share_url"],
        "checks": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    return verification


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the GEO MVP demo loop end to end.")
    parser.add_argument("--summary", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_VERIFY_OUTPUT)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--web-base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--refresh-demo", action="store_true")
    parser.add_argument("--reset-demo", action="store_true")
    args = parser.parse_args()

    verify_demo(
        summary_path=args.summary,
        output_path=args.output,
        api_base_url=args.api_base_url.rstrip("/"),
        web_base_url=args.web_base_url.rstrip("/"),
        refresh_demo=args.refresh_demo,
        reset_demo=args.reset_demo,
    )


if __name__ == "__main__":
    main()
