import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_real_provider_smoke import DEFAULT_OUTPUT as REAL_SMOKE_OUTPUT
from run_real_provider_smoke import run_smoke
from run_e2e_demo import run_demo
from verify_alert_action_goals_testclient import DEFAULT_OUTPUT as ALERT_ACTION_GOALS_OUTPUT
from verify_alert_action_goals_testclient import verify_alert_action_goals
from verify_analysis_correction_testclient import DEFAULT_OUTPUT as ANALYSIS_CORRECTION_OUTPUT
from verify_analysis_correction_testclient import verify_analysis_correction
from verify_article_source_context_testclient import DEFAULT_OUTPUT as ARTICLE_SOURCE_CONTEXT_OUTPUT
from verify_article_source_context_testclient import verify_article_source_context
from verify_bulk_high_score_draft_approval_testclient import (
    DEFAULT_OUTPUT as BULK_HIGH_SCORE_APPROVAL_OUTPUT,
)
from verify_bulk_high_score_draft_approval_testclient import verify_bulk_high_score_draft_approval
from verify_browser_observation_evidence_testclient import (
    DEFAULT_OUTPUT as BROWSER_OBSERVATION_EVIDENCE_OUTPUT,
)
from verify_browser_observation_evidence_testclient import verify_browser_observation_evidence
from verify_browser_observation_to_draft_loop_testclient import (
    DEFAULT_OUTPUT as BROWSER_OBSERVATION_TO_DRAFT_LOOP_OUTPUT,
)
from verify_browser_observation_to_draft_loop_testclient import verify_browser_observation_to_draft_loop
from verify_browser_observation_pack_gap_selection_testclient import (
    DEFAULT_OUTPUT as BROWSER_OBSERVATION_PACK_GAP_SELECTION_OUTPUT,
)
from verify_browser_observation_pack_gap_selection_testclient import verify_pack_gap_selection
from verify_import_browser_observation_evidence_dir_testclient import (
    DEFAULT_OUTPUT as IMPORT_BROWSER_OBSERVATION_EVIDENCE_DIR_OUTPUT,
)
from verify_import_browser_observation_evidence_dir_testclient import verify_import_browser_observation_evidence_dir
from verify_content_delivery_loop_testclient import DEFAULT_OUTPUT as CONTENT_DELIVERY_OUTPUT
from verify_content_delivery_loop_testclient import verify_content_delivery_loop
from verify_content_remediation_goals_testclient import DEFAULT_OUTPUT as CONTENT_REMEDIATION_OUTPUT
from verify_content_remediation_goals_testclient import verify_content_remediation_goals
from verify_crawl_estimate_cost_testclient import DEFAULT_OUTPUT as CRAWL_ESTIMATE_COST_OUTPUT
from verify_crawl_estimate_cost_testclient import verify_crawl_estimate_cost
from verify_diagnostic_run_testclient import DEFAULT_OUTPUT as DIAGNOSTIC_RUN_OUTPUT
from verify_diagnostic_run_testclient import verify_diagnostic_run
from verify_demo_provider_evidence_testclient import DEFAULT_OUTPUT as DEMO_PROVIDER_EVIDENCE_OUTPUT
from verify_demo_provider_evidence_testclient import verify_demo_provider_evidence
from verify_mvp_status_testclient import DEFAULT_OUTPUT as MVP_STATUS_OUTPUT
from verify_mvp_status_testclient import verify_mvp_status
from verify_monitoring_alerts_testclient import DEFAULT_OUTPUT as MONITORING_ALERTS_OUTPUT
from verify_monitoring_alerts_testclient import verify_monitoring_alerts
from verify_placement_impact_goals_testclient import DEFAULT_OUTPUT as PLACEMENT_IMPACT_GOALS_OUTPUT
from verify_placement_impact_goals_testclient import verify_placement_impact_goals
from verify_project_dashboard_testclient import DEFAULT_OUTPUT as PROJECT_DASHBOARD_OUTPUT
from verify_project_dashboard_testclient import verify_project_dashboard
from verify_provider_collection_summary_testclient import DEFAULT_OUTPUT as PROVIDER_COLLECTION_OUTPUT
from verify_provider_collection_summary_testclient import verify_provider_collection_summary
from verify_report_evidence_testclient import DEFAULT_OUTPUT as REPORT_EVIDENCE_OUTPUT
from verify_report_evidence_testclient import verify_report_evidence
from verify_report_bulk_drafts_testclient import DEFAULT_OUTPUT as REPORT_BULK_DRAFTS_OUTPUT
from verify_report_bulk_drafts_testclient import verify_report_bulk_drafts
from verify_real_provider_diagnostic_flow_testclient import DEFAULT_OUTPUT as REAL_PROVIDER_DIAGNOSTIC_OUTPUT
from verify_real_provider_diagnostic_flow_testclient import verify_real_provider_diagnostic_flow
from verify_report_templates_testclient import DEFAULT_OUTPUT as REPORT_TEMPLATES_OUTPUT
from verify_report_templates_testclient import verify_report_templates
from verify_report_action_goals_testclient import DEFAULT_OUTPUT as REPORT_ACTION_GOALS_OUTPUT
from verify_report_action_goals_testclient import verify_report_action_goals
from verify_review_rules_testclient import DEFAULT_OUTPUT as REVIEW_RULES_OUTPUT
from verify_review_rules_testclient import verify_review_rules
from verify_schedule_queue_loop_testclient import DEFAULT_OUTPUT as SCHEDULE_QUEUE_OUTPUT
from verify_schedule_queue_loop_testclient import verify_schedule_queue_loop
from verify_source_intelligence_testclient import DEFAULT_OUTPUT as SOURCE_INTELLIGENCE_OUTPUT
from verify_source_intelligence_testclient import verify_source_intelligence


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_local_acceptance_suite.json"


def _step_ok(result: dict[str, Any]) -> bool:
    return result.get("ok") is True


def _seed_isolated_acceptance_fixture(project_id: int) -> None:
    """Seed the legacy no-port suite without relying on a historical developer DB.

    Several legacy verifier scripts intentionally assert the old demo project's
    numeric IDs (project 9 and provider IDs 9/10/12). Keep that compatibility
    local to this fixture while making its provenance explicit and disposable.
    """
    from app.db.session import SessionLocal
    from app.models import AnswerAnalysis, CrawlResult, CrawlSchedule, CrawlTask, LLMProvider, LLMProviderTestRun, PlacementRecord, Project, TargetQuestion, User

    first_demo = run_demo()
    if first_demo["project_id"] > project_id:
        raise RuntimeError(f"Unable to create legacy fixture project #{project_id}")

    with SessionLocal() as db:
        company_id = int(first_demo["company_id"])
        while (db.scalar(select(func.count()).select_from(Project)) or 0) < project_id - 1:
            db.add(
                Project(
                    company_id=company_id,
                    name="Isolated acceptance fixture placeholder",
                    status="archived",
                )
            )
            db.flush()
        db.commit()

    demo = first_demo if int(first_demo["project_id"]) == project_id else run_demo()
    if int(demo["project_id"]) != project_id:
        raise RuntimeError(f"Legacy fixture project ID mismatch: {demo['project_id']} != {project_id}")

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        user = db.scalar(select(User).where(User.email == "geo-demo-e2e@example.com"))
        question = db.scalar(
            select(TargetQuestion).where(TargetQuestion.project_id == project_id).order_by(TargetQuestion.id.asc())
        )
        if project is None or user is None or question is None:
            raise RuntimeError("Legacy fixture is missing its project, user, or target question")

        providers: dict[int, LLMProvider] = {}
        while (db.scalar(select(func.max(LLMProvider.id))) or 0) < 12:
            next_id = int((db.scalar(select(func.max(LLMProvider.id))) or 0) + 1)
            is_verified_provider = next_id in {9, 12}
            provider = LLMProvider(
                name=f"Isolated acceptance provider {next_id}",
                provider_type="openai_compatible" if next_id in {9, 10, 12} else "mock",
                model_name=f"fixture-model-{next_id}",
                api_base_url="https://fixture.invalid/v1" if next_id in {9, 10, 12} else None,
                # This is a short-lived test marker, not a usable credential.
                auth_config={"api_key": "fixture-not-a-secret"} if next_id in {9, 10, 12} else {},
                cost_rule={"input_per_1k": 0, "output_per_1k": 0, "currency": "USD"},
                status="active",
            )
            db.add(provider)
            db.flush()
            providers[next_id] = provider
            if is_verified_provider:
                db.add(
                    LLMProviderTestRun(
                        provider_id=provider.id,
                        actor_user_id=user.id,
                        ok=True,
                        prompt_text="Isolated local acceptance fixture",
                        company_name=project.company.name,
                        industry=project.target_industry,
                        answer_summary="Fixture provider readiness confirmation.",
                        raw_answer_preview="Fixture provider readiness confirmation.",
                        latency_ms=1,
                    )
                )

        for provider_id in (9, 12):
            provider = db.get(LLMProvider, provider_id)
            if provider is None:
                raise RuntimeError(f"Fixture provider #{provider_id} was not created")
            task = CrawlTask(
                project_id=project.id,
                task_type="isolated_acceptance_fixture",
                schedule_type="manual",
                provider_ids=[provider.id],
                target_question_ids=[question.id],
                keyword_ids=[],
                status="success",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            db.add(task)
            db.flush()
            for sample_index in range(3):
                result = CrawlResult(
                    task_id=task.id,
                    project_id=project.id,
                    target_question_id=question.id,
                    provider_id=provider.id,
                    prompt_text=question.question_text,
                    raw_answer=f"{project.company.name} 是测试夹具中的可见品牌证据（复测 {sample_index + 1}）。",
                    answer_summary="Isolated acceptance fixture result.",
                    status="success",
                    collected_at=datetime.now(UTC),
                )
                db.add(result)
                db.flush()
                db.add(
                    AnswerAnalysis(
                        crawl_result_id=result.id,
                        company_mentioned=True,
                        company_recommended=True,
                        company_rank=1,
                        sentiment="positive",
                        confidence=100,
                        analysis_json={"method": "isolated_acceptance_fixture"},
                    )
                )

        existing_platforms = {
            str(provider.cost_rule.get("platform_name") or provider.name)
            for provider in db.scalars(
                select(LLMProvider)
                .where(LLMProvider.provider_type == "browser_observation")
                .where(LLMProvider.status == "active")
            )
        }
        for platform_name in ("豆包", "DeepSeek", "Kimi", "千问"):
            if platform_name not in existing_platforms:
                db.add(
                    LLMProvider(
                        name=f"{platform_name} 网页端观测夹具",
                        provider_type="browser_observation",
                        model_name="browser-observation",
                        api_base_url="https://fixture.invalid/browser-observation",
                        cost_rule={"platform_name": platform_name},
                        status="active",
                    )
                )

        failed_provider = db.get(LLMProvider, 10)
        if failed_provider is None:
            raise RuntimeError("Fixture provider #10 was not created")
        db.add(
            CrawlTask(
                project_id=project.id,
                task_type="isolated_acceptance_fixture",
                schedule_type="manual",
                provider_ids=[failed_provider.id],
                target_question_ids=[question.id],
                keyword_ids=[],
                status="failed",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                error_message="Fixture timeout for failed-task UI coverage.",
            )
        )
        if db.scalar(select(func.count()).select_from(CrawlSchedule).where(CrawlSchedule.project_id == project.id)) == 0:
            db.add(
                CrawlSchedule(
                    project_id=project.id,
                    name="Isolated acceptance active schedule",
                    schedule_type="weekly",
                    interval_hours=24 * 7,
                    provider_ids=[9, 12],
                    target_question_ids=[question.id],
                    keyword_ids=[],
                    status="active",
                    last_run_at=datetime.now(UTC),
                    next_run_at=datetime.now(UTC),
                )
            )
        placement = db.scalar(
            select(PlacementRecord)
            .where(PlacementRecord.project_id == project.id)
            .order_by(PlacementRecord.published_at.desc())
            .limit(1)
        )
        if placement is not None:
            placement.published_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()


def run_local_acceptance_suite(
    *,
    project_id: int,
    email: str,
    password: str,
    output_path: Path,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    mvp_status = verify_mvp_status(
        project_id=project_id,
        email=email,
        password=password,
        output_path=MVP_STATUS_OUTPUT,
    )
    content_delivery = verify_content_delivery_loop(
        project_id=project_id,
        output_path=CONTENT_DELIVERY_OUTPUT,
    )
    bulk_high_score_approval = verify_bulk_high_score_draft_approval(output_path=BULK_HIGH_SCORE_APPROVAL_OUTPUT)
    content_remediation = verify_content_remediation_goals(output_path=CONTENT_REMEDIATION_OUTPUT)
    schedule_queue = verify_schedule_queue_loop(output_path=SCHEDULE_QUEUE_OUTPUT)
    crawl_estimate_cost = verify_crawl_estimate_cost(output_path=CRAWL_ESTIMATE_COST_OUTPUT)
    diagnostic_run = verify_diagnostic_run(output_path=DIAGNOSTIC_RUN_OUTPUT)
    monitoring_alerts = verify_monitoring_alerts(output_path=MONITORING_ALERTS_OUTPUT)
    alert_action_goals = verify_alert_action_goals(output_path=ALERT_ACTION_GOALS_OUTPUT)
    project_dashboard = verify_project_dashboard(project_id=project_id, email=email, password=password, output_path=PROJECT_DASHBOARD_OUTPUT)
    demo_provider_evidence = verify_demo_provider_evidence(
        project_id=project_id,
        email=email,
        password=password,
        output_path=DEMO_PROVIDER_EVIDENCE_OUTPUT,
    )
    provider_collection = verify_provider_collection_summary(output_path=PROVIDER_COLLECTION_OUTPUT)
    review_rules = verify_review_rules(output_path=REVIEW_RULES_OUTPUT)
    report_templates = verify_report_templates(output_path=REPORT_TEMPLATES_OUTPUT)
    report_evidence = verify_report_evidence(output_path=REPORT_EVIDENCE_OUTPUT)
    report_bulk_drafts = verify_report_bulk_drafts(output_path=REPORT_BULK_DRAFTS_OUTPUT)
    real_provider_diagnostic = verify_real_provider_diagnostic_flow(output_path=REAL_PROVIDER_DIAGNOSTIC_OUTPUT)
    report_action_goals = verify_report_action_goals(output_path=REPORT_ACTION_GOALS_OUTPUT)
    placement_impact_goals = verify_placement_impact_goals(output_path=PLACEMENT_IMPACT_GOALS_OUTPUT)
    article_source_context = verify_article_source_context(
        project_id=project_id,
        email=email,
        password=password,
        output_path=ARTICLE_SOURCE_CONTEXT_OUTPUT,
    )
    source_intelligence = verify_source_intelligence(output_path=SOURCE_INTELLIGENCE_OUTPUT)
    browser_observation_evidence = verify_browser_observation_evidence(output_path=BROWSER_OBSERVATION_EVIDENCE_OUTPUT)
    browser_observation_to_draft_loop = verify_browser_observation_to_draft_loop(
        output_path=BROWSER_OBSERVATION_TO_DRAFT_LOOP_OUTPUT
    )
    browser_observation_pack_gap_selection = verify_pack_gap_selection(
        output_path=BROWSER_OBSERVATION_PACK_GAP_SELECTION_OUTPUT
    )
    import_browser_observation_evidence_dir = verify_import_browser_observation_evidence_dir(
        output_path=IMPORT_BROWSER_OBSERVATION_EVIDENCE_DIR_OUTPUT
    )
    analysis_correction = verify_analysis_correction(output_path=ANALYSIS_CORRECTION_OUTPUT)
    real_provider_smoke = run_smoke(
        project_id=project_id,
        provider_ids=[9, 12],
        question_limit=1,
        keyword_limit=0,
        dry_run=True,
        output_path=REAL_SMOKE_OUTPUT,
    )
    steps = [
        {
            "name": "mvp_status_testclient",
            "ok": _step_ok(mvp_status),
            "output": str(MVP_STATUS_OUTPUT),
            "summary": {
                "mvp_status_ok": mvp_status.get("mvp_status_ok"),
                "crawl_health": (mvp_status.get("crawl_health") or {}).get("status"),
                "content_delivery_ok": (mvp_status.get("content_delivery") or {}).get("ok"),
            },
        },
        {
            "name": "content_delivery_loop_testclient",
            "ok": _step_ok(content_delivery),
            "output": str(CONTENT_DELIVERY_OUTPUT),
            "summary": {
                "draft_status": (content_delivery.get("draft") or {}).get("status"),
                "review_grade": (content_delivery.get("ai_review") or {}).get("grade"),
                "placement_status": (content_delivery.get("placement") or {}).get("status"),
                "delivery_status": (content_delivery.get("placement") or {}).get("delivery_status"),
            },
        },
        {
            "name": "bulk_high_score_draft_approval_testclient",
            "ok": _step_ok(bulk_high_score_approval),
            "output": str(BULK_HIGH_SCORE_APPROVAL_OUTPUT),
            "summary": {
                "approved_count": bulk_high_score_approval.get("approved_count"),
                "low_score_preserved": bulk_high_score_approval.get("low_score_preserved"),
                "threshold": bulk_high_score_approval.get("threshold"),
            },
        },
        {
            "name": "content_remediation_goals_testclient",
            "ok": _step_ok(content_remediation),
            "output": str(CONTENT_REMEDIATION_OUTPUT),
            "summary": {
                "review_score": content_remediation.get("review_score"),
                "created_goal_count": content_remediation.get("created_goal_count"),
                "second_call_created_goal_count": content_remediation.get("second_call_created_goal_count"),
                "suggested_actions": content_remediation.get("suggested_actions"),
            },
        },
        {
            "name": "schedule_queue_loop_testclient",
            "ok": _step_ok(schedule_queue),
            "output": str(SCHEDULE_QUEUE_OUTPUT),
            "summary": {
                "schedule_status": (schedule_queue.get("schedule") or {}).get("status"),
                "job_status": (schedule_queue.get("worker") or {}).get("job_status"),
                "task_status": (schedule_queue.get("worker") or {}).get("task_status"),
                "result_count": (schedule_queue.get("worker") or {}).get("result_count"),
            },
        },
        {
            "name": "crawl_estimate_cost_testclient",
            "ok": _step_ok(crawl_estimate_cost),
            "output": str(CRAWL_ESTIMATE_COST_OUTPUT),
            "summary": {
                "prompt_count": crawl_estimate_cost.get("prompt_count"),
                "total_call_count": crawl_estimate_cost.get("total_call_count"),
                "estimated_total_tokens": crawl_estimate_cost.get("estimated_total_tokens"),
                "estimated_cost": crawl_estimate_cost.get("estimated_cost"),
                "cost_configured_provider_count": crawl_estimate_cost.get("cost_configured_provider_count"),
            },
        },
        {
            "name": "diagnostic_run_testclient",
            "ok": _step_ok(diagnostic_run),
            "output": str(DIAGNOSTIC_RUN_OUTPUT),
            "summary": {
                "provider_count": diagnostic_run.get("provider_count"),
                "target_question_count": diagnostic_run.get("target_question_count"),
                "keyword_count": diagnostic_run.get("keyword_count"),
                "expected_call_count": diagnostic_run.get("expected_call_count"),
                "result_count": diagnostic_run.get("result_count"),
                "report_id": diagnostic_run.get("report_id"),
                "created_goal_count": diagnostic_run.get("created_goal_count"),
            },
        },
        {
            "name": "monitoring_alerts_testclient",
            "ok": _step_ok(monitoring_alerts),
            "output": str(MONITORING_ALERTS_OUTPUT),
            "summary": {
                "created_alert_count": monitoring_alerts.get("created_alert_count"),
                "alert_types": monitoring_alerts.get("alert_types"),
                "second_call_created_alert_count": monitoring_alerts.get("second_call_created_alert_count"),
            },
        },
        {
            "name": "alert_action_goals_testclient",
            "ok": _step_ok(alert_action_goals),
            "output": str(ALERT_ACTION_GOALS_OUTPUT),
            "summary": {
                "created_goal_count": alert_action_goals.get("created_goal_count"),
                "second_call_status": alert_action_goals.get("second_call_status"),
                "alert_status_after_action": alert_action_goals.get("alert_status_after_action"),
            },
        },
        {
            "name": "project_dashboard_testclient",
            "ok": _step_ok(project_dashboard),
            "output": str(PROJECT_DASHBOARD_OUTPUT),
            "summary": {
                "dashboard_route": project_dashboard.get("dashboard_route"),
                "mvp_status_ok": project_dashboard.get("mvp_status_ok"),
                "provider_mode": project_dashboard.get("provider_mode"),
                "trend_point_count": project_dashboard.get("trend_point_count"),
                "priority_action_keys": project_dashboard.get("priority_action_keys"),
            },
        },
        {
            "name": "demo_provider_evidence_testclient",
            "ok": _step_ok(demo_provider_evidence),
            "output": str(DEMO_PROVIDER_EVIDENCE_OUTPUT),
            "summary": {
                "demo_route": demo_provider_evidence.get("demo_route"),
                "provider_mode": demo_provider_evidence.get("provider_mode"),
                "real_collection_ready": demo_provider_evidence.get("real_collection_ready"),
                "provider_ids": sorted((demo_provider_evidence.get("provider_evidence") or {}).keys()),
            },
        },
        {
            "name": "provider_collection_summary_testclient",
            "ok": _step_ok(provider_collection),
            "output": str(PROVIDER_COLLECTION_OUTPUT),
            "summary": provider_collection.get("provider_summaries"),
        },
        {
            "name": "review_rules_testclient",
            "ok": _step_ok(review_rules),
            "output": str(REVIEW_RULES_OUTPUT),
            "summary": {
                "active_rule_count": review_rules.get("active_rule_count"),
                "dimension_count": (review_rules.get("review") or {}).get("dimension_count"),
                "snapshot_rule_count": (review_rules.get("review") or {}).get("snapshot_rule_count"),
                "review_grade": (review_rules.get("review") or {}).get("grade"),
            },
        },
        {
            "name": "report_templates_testclient",
            "ok": _step_ok(report_templates),
            "output": str(REPORT_TEMPLATES_OUTPUT),
            "summary": {
                "default_template_key": report_templates.get("default_template_key"),
                "snapshot_template_key": report_templates.get("snapshot_template_key"),
                "snapshot_version": report_templates.get("snapshot_version"),
                "template_dimension_count": report_templates.get("template_dimension_count"),
                "matched_dimension_count": report_templates.get("matched_dimension_count"),
                "unmatched_template_dimension_count": report_templates.get("unmatched_template_dimension_count"),
                "markdown_has_template_line": report_templates.get("markdown_has_template_line"),
            },
        },
        {
            "name": "report_evidence_testclient",
            "ok": _step_ok(report_evidence),
            "output": str(REPORT_EVIDENCE_OUTPUT),
            "summary": {
                "evidence_sample_count": report_evidence.get("evidence_sample_count"),
                "score_item_count": report_evidence.get("score_item_count"),
                "markdown_has_evidence_appendix": report_evidence.get("markdown_has_evidence_appendix"),
                "brand_matrix_summary_count": report_evidence.get("brand_matrix_summary_count"),
                "markdown_has_brand_matrix": report_evidence.get("markdown_has_brand_matrix"),
                "delivery_readiness_status": report_evidence.get("delivery_readiness_status"),
                "markdown_has_delivery_readiness": report_evidence.get("markdown_has_delivery_readiness"),
                "real_api_sample_count": report_evidence.get("real_api_sample_count"),
                "mock_sample_count": report_evidence.get("mock_sample_count"),
                "real_provider_count": report_evidence.get("real_provider_count"),
                "keyword_prompt_variant_count": report_evidence.get("keyword_prompt_variant_count"),
                "markdown_has_keyword_prompt_coverage": report_evidence.get("markdown_has_keyword_prompt_coverage"),
                "markdown_has_real_sample_quality": report_evidence.get("markdown_has_real_sample_quality"),
            },
        },
        {
            "name": "report_bulk_drafts_testclient",
            "ok": _step_ok(report_bulk_drafts),
            "output": str(REPORT_BULK_DRAFTS_OUTPUT),
            "summary": {
                "topic_count": report_bulk_drafts.get("topic_count"),
                "draft_count": report_bulk_drafts.get("draft_count"),
                "review_count": report_bulk_drafts.get("review_count"),
                "source_report_bound": report_bulk_drafts.get("source_report_bound"),
            },
        },
        {
            "name": "real_provider_diagnostic_preflight_testclient",
            "ok": _step_ok(real_provider_diagnostic),
            "output": str(REAL_PROVIDER_DIAGNOSTIC_OUTPUT),
            "summary": {
                "task_status": real_provider_diagnostic.get("task_status"),
                "expected_call_count": real_provider_diagnostic.get("expected_call_count"),
                "result_count": real_provider_diagnostic.get("result_count"),
                "blocked_without_real_api_key": (real_provider_diagnostic.get("safety") or {}).get("blocked_without_real_api_key"),
            },
        },
        {
            "name": "report_action_goals_testclient",
            "ok": _step_ok(report_action_goals),
            "output": str(REPORT_ACTION_GOALS_OUTPUT),
            "summary": {
                "created_goal_count": report_action_goals.get("created_goal_count"),
                "has_delivery_readiness_goal": report_action_goals.get("has_delivery_readiness_goal"),
                "delivery_goal_suggested_actions": report_action_goals.get("delivery_goal_suggested_actions"),
                "second_call_created_goal_count": report_action_goals.get("second_call_created_goal_count"),
                "tracked_goal_count": report_action_goals.get("tracked_goal_count"),
                "tracking_has_progress": report_action_goals.get("tracking_has_progress"),
            },
        },
        {
            "name": "placement_impact_goals_testclient",
            "ok": _step_ok(placement_impact_goals),
            "output": str(PLACEMENT_IMPACT_GOALS_OUTPUT),
            "summary": {
                "impact_status": placement_impact_goals.get("impact_status"),
                "created_goal_count": placement_impact_goals.get("created_goal_count"),
                "metric_keys": placement_impact_goals.get("created_goal_metric_keys"),
                "second_call_created_goal_count": placement_impact_goals.get("second_call_created_goal_count"),
                "has_suggested_crawl_action": placement_impact_goals.get("has_suggested_crawl_action"),
            },
        },
        {
            "name": "article_source_context_testclient",
            "ok": _step_ok(article_source_context),
            "output": str(ARTICLE_SOURCE_CONTEXT_OUTPUT),
            "summary": {
                "source_report_id": (article_source_context.get("source_context") or {}).get("source_report_id"),
                "topic_source": (article_source_context.get("source_context") or {}).get("topic_source"),
                "stage_goal_id": (article_source_context.get("source_context") or {}).get("stage_goal_id"),
                "source_gap_count": (article_source_context.get("source_context") or {}).get("source_gap_count"),
                "keyword_prompt_gap_count": (article_source_context.get("source_context") or {}).get("keyword_prompt_gap_count"),
                "keyword_prompt_sample_count": (article_source_context.get("source_context") or {}).get("keyword_prompt_sample_count"),
                "revision_of_draft_id": (article_source_context.get("revision_context") or {}).get("revision_of_draft_id"),
            },
        },
        {
            "name": "source_intelligence_testclient",
            "ok": _step_ok(source_intelligence),
            "output": str(SOURCE_INTELLIGENCE_OUTPUT),
            "summary": {
                "placement_count": (source_intelligence.get("insight") or {}).get("placement_count"),
                "published_placement_count": (source_intelligence.get("insight") or {}).get("published_placement_count"),
                "ai_readiness_status": (source_intelligence.get("insight") or {}).get("ai_readiness_status"),
            },
        },
        {
            "name": "browser_observation_evidence_testclient",
            "ok": _step_ok(browser_observation_evidence),
            "output": str(BROWSER_OBSERVATION_EVIDENCE_OUTPUT),
            "summary": {
                "source_count": (browser_observation_evidence.get("observation") or {}).get("source_count"),
                "screenshot_evidence_count": (browser_observation_evidence.get("observation") or {}).get(
                    "screenshot_evidence_count"
                ),
                "browser_observation_count": (browser_observation_evidence.get("evidence_quality") or {}).get(
                    "browser_observation_count"
                ),
                "browser_observation_rate": (browser_observation_evidence.get("evidence_quality") or {}).get(
                    "browser_observation_rate"
                ),
            },
        },
        {
            "name": "browser_observation_to_draft_loop_testclient",
            "ok": _step_ok(browser_observation_to_draft_loop),
            "output": str(BROWSER_OBSERVATION_TO_DRAFT_LOOP_OUTPUT),
            "summary": {
                "platforms": browser_observation_to_draft_loop.get("platforms"),
                "browser_observation_platform_count": (
                    browser_observation_to_draft_loop.get("evidence_quality") or {}
                ).get("browser_observation_platform_count"),
                "screenshot_evidence_count": (
                    browser_observation_to_draft_loop.get("evidence_quality") or {}
                ).get("screenshot_evidence_count"),
                "source_report_bound": (browser_observation_to_draft_loop.get("draft") or {}).get(
                    "source_report_bound"
                ),
                "browser_observation_result_ids_bound": (
                    browser_observation_to_draft_loop.get("draft") or {}
                ).get("browser_observation_result_ids_bound"),
                "review_grade": (browser_observation_to_draft_loop.get("review") or {}).get("grade"),
            },
        },
        {
            "name": "import_browser_observation_evidence_dir_testclient",
            "ok": _step_ok(import_browser_observation_evidence_dir),
            "output": str(IMPORT_BROWSER_OBSERVATION_EVIDENCE_DIR_OUTPUT),
            "summary": {
                "archived_file_count": import_browser_observation_evidence_dir.get("archived_file_count"),
                "archive_dir": import_browser_observation_evidence_dir.get("archive_dir"),
                "report_platform_count": (import_browser_observation_evidence_dir.get("report") or {}).get(
                    "browser_observation_platform_count"
                ),
                "review_grade": (import_browser_observation_evidence_dir.get("review") or {}).get("grade"),
            },
        },
        {
            "name": "browser_observation_pack_gap_selection_testclient",
            "ok": _step_ok(browser_observation_pack_gap_selection),
            "output": str(BROWSER_OBSERVATION_PACK_GAP_SELECTION_OUTPUT),
            "summary": {
                "covered_question_id": browser_observation_pack_gap_selection.get("covered_question_id"),
                "next_question_id": browser_observation_pack_gap_selection.get("next_question_id"),
                "observation_count": browser_observation_pack_gap_selection.get("observation_count"),
                "evidence_filenames": browser_observation_pack_gap_selection.get("evidence_filenames"),
            },
        },
        {
            "name": "analysis_correction_testclient",
            "ok": _step_ok(analysis_correction),
            "output": str(ANALYSIS_CORRECTION_OUTPUT),
            "summary": {
                "company_mentioned": (analysis_correction.get("analysis") or {}).get("company_mentioned"),
                "company_recommended": (analysis_correction.get("analysis") or {}).get("company_recommended"),
                "has_manual_correction": (analysis_correction.get("analysis") or {}).get("has_manual_correction"),
            },
        },
        {
            "name": "real_provider_smoke_dry_run",
            "ok": _step_ok(real_provider_smoke),
            "output": str(REAL_SMOKE_OUTPUT),
            "summary": {
                "planned_call_count": real_provider_smoke.get("planned_call_count"),
                "provider_ids": real_provider_smoke.get("provider_ids"),
                "dry_run": real_provider_smoke.get("dry_run"),
            },
        },
    ]
    result = {
        "ok": all(step["ok"] for step in steps),
        "verification_method": "local no-port acceptance suite",
        "project_id": project_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "steps": steps,
        "limitations": [
            "This suite does not bind local API/Web ports.",
            "The real-provider smoke check is a dry-run by default to avoid network/API-token consumption in restricted Codex environments.",
            "Run scripts/run_real_provider_smoke.py without --dry-run in a network-approved environment for live Ark/DeepSeek collection.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise AssertionError(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local GEO MVP acceptance suite without binding ports.")
    parser.add_argument("--project-id", type=int, default=9)
    parser.add_argument("--email", default="geo-demo-e2e@example.com")
    parser.add_argument("--password", default="geo-demo-123")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    # The suite imports API modules directly through TestClient. Without an explicit
    # bootstrap it used the developer's default SQLite file and failed on a clean
    # machine before the first assertion. Re-exec once with a disposable database
    # so local verification is reproducible and never mutates a developer DB.
    if not os.environ.get("DATABASE_URL") and os.environ.get("GEO_ACCEPTANCE_ISOLATED") != "1":
        with tempfile.TemporaryDirectory(prefix="geo-local-acceptance-") as temp_dir:
            database_path = Path(temp_dir) / "acceptance.sqlite3"
            env = {
                **os.environ,
                "DATABASE_URL": f"sqlite:///{database_path}",
                "GEO_ACCEPTANCE_ISOLATED": "1",
                "AUTO_CREATE_TABLES": "false",
            }
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
                env=env,
                check=False,
            )
            raise SystemExit(completed.returncode)

    # All model modules have already been imported by the verifier modules above.
    # Create the schema explicitly because a direct TestClient call does not enter
    # FastAPI's lifespan handler.
    from app import models  # noqa: F401
    from app.db.session import Base, engine

    Base.metadata.create_all(bind=engine)
    if os.environ.get("GEO_ACCEPTANCE_ISOLATED") == "1":
        _seed_isolated_acceptance_fixture(args.project_id)
    run_local_acceptance_suite(
        project_id=args.project_id,
        email=args.email,
        password=args.password,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
