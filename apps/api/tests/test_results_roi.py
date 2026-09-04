from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import create_app
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoActionOpportunity,
    GeoBusinessMetricEntry,
    GeoOptimizationAction,
    GeoQuestionPlan,
    GeoReobservation,
    GeoWorkspace,
)
from app.models.user import User
from app.models.workspace_access import WorkspaceMembership
from app.services.workspace_access import add_membership


@pytest.fixture
def results_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(Company(id=1, name="测试企业"))
        db.add(
            User(
                id=1,
                company_id=1,
                name="企业管理员",
                email="roi@example.com",
                role="company_admin",
            )
        )
        db.add(
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="roi-workspace",
                brand_name="春秋元泉",
                brand_aliases=[],
            )
        )
        db.add(
            GeoQuestionPlan(
                id=1,
                workspace_id=1,
                question_text="企业如何选择 GEO 服务？",
                journey_stage="consideration",
                role="business_owner",
                topic_tags=[],
                importance=5,
                is_brand_query=False,
                active=True,
                status="active",
                source_type="manual",
                source_evidence={},
                template_variables=[],
            )
        )
        db.add(
            GeoActionOpportunity(
                id=1,
                workspace_id=1,
                fingerprint="b" * 64,
                opportunity_type="candidate_gap",
                title="补齐品牌答案",
                summary="品牌未进入推荐",
                priority_score=90,
                priority_label="high",
                evidence_strength=1,
                recommended_asset_type="article",
                recommended_platforms=["zhihu"],
                scope_snapshot={},
                rule_version="opportunity.v1",
                status="selected",
            )
        )
        db.add(
            GeoOptimizationAction(
                id=1,
                workspace_id=1,
                opportunity_id=1,
                question_plan_id=1,
                title="补齐品牌答案",
                rationale="品牌未进入推荐",
                priority="high",
                status="verified",
                stage="verified",
                baseline_snapshot={"batch_id": 10},
                selected_scope={},
                measurement_plan={
                    "schema": "action-measurement/v1",
                    "primary_metric": "impact_score",
                    "primary_metric_label": "综合影响分",
                    "direction": "higher",
                    "minimum_comparable_rounds_for_stability": 2,
                    "minimum_model_agreement": 0.5,
                    "baseline_batch_id": 10,
                    "principle": "同口径复测",
                },
            )
        )
        baseline = {
            "impact_score": 0.1,
            "by_model": {
                "deepseek": {"eligible": 2, "positive": 0},
                "qwen": {"eligible": 2, "positive": 0},
            },
        }
        for round_index, score in ((1, 0.3), (2, 0.4)):
            db.add(
                GeoReobservation(
                    action_id=1,
                    workspace_id=1,
                    round_index=round_index,
                    baseline_batch_id=10,
                    retest_batch_id=10 + round_index,
                    status="completed",
                    scope_snapshot={},
                    baseline_metrics=baseline,
                    retest_metrics={
                        "impact_score": score,
                        "by_model": {
                            "deepseek": {"eligible": 2, "positive": 1},
                            "qwen": {"eligible": 2, "positive": 0},
                        },
                    },
                    conclusion="improved",
                    measured_delta={"comparable": True, "impact_score": score - 0.1},
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
        db.flush()
        add_membership(db, workspace_id=1, user_id=1, role="owner")
        db.commit()

    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    current = SimpleNamespace(id=1, company_id=1, role="company_admin")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current
    client = TestClient(app)
    client.app.state.results_sessions = sessions
    client.app.state.results_user = current
    yield client
    app.dependency_overrides.clear()


def test_effect_overview_uses_persisted_multi_round_evidence_without_get_side_effects(
    results_client: TestClient,
) -> None:
    sessions = results_client.app.state.results_sessions
    with sessions() as db:
        before = db.scalar(select(func.count()).select_from(GeoReobservation))
    response = results_client.get("/api/v1/workspaces/1/results-overview")
    assert response.status_code == 200
    payload = response.json()
    action = payload["effect"]["actions"][0]
    assert action["outcome"]["status"] == "stable_improvement"
    assert action["outcome"]["comparable_rounds"] == 2
    assert action["outcome"]["model_agreement"] == 0.5
    assert [point["round_index"] for point in action["trend"]] == [0, 1, 2]
    with sessions() as db:
        after = db.scalar(select(func.count()).select_from(GeoReobservation))
    assert after == before


def test_effect_overview_applies_real_filter_contract(results_client: TestClient) -> None:
    response = results_client.get(
        "/api/v1/workspaces/1/results-overview?period_days=90&question_plan_id=1"
    )
    assert response.status_code == 200
    payload = response.json()["effect"]
    assert payload["historical"]["filters"] == {
        "period_days": 90,
        "model_key": None,
        "question_plan_id": 1,
        "question_plan_ids": [1],
    }
    assert [action["action_id"] for action in payload["actions"]] == [1]


def test_effect_overview_accepts_multiple_question_scope(results_client: TestClient) -> None:
    response = results_client.get(
        "/api/v1/workspaces/1/results-overview?question_plan_ids=1&question_plan_ids=2"
    )
    assert response.status_code == 200
    payload = response.json()["effect"]
    assert payload["historical"]["filters"]["question_plan_ids"] == [1, 2]
    assert [action["action_id"] for action in payload["actions"]] == [1]


def test_effect_overview_accepts_multiple_model_scope(results_client: TestClient) -> None:
    response = results_client.get(
        "/api/v1/workspaces/1/results-overview?model_keys=deepseek&model_keys=qwen"
    )
    assert response.status_code == 200
    assert response.json()["effect"]["historical"]["filters"]["model_keys"] == [
        "deepseek",
        "qwen",
    ]


def test_business_goal_is_persisted_and_read_back_without_inventing_measurements(
    results_client: TestClient,
) -> None:
    assert results_client.get("/api/v1/workspaces/1/business-goal").json() is None

    saved = results_client.put(
        "/api/v1/workspaces/1/business-goal",
        json={
            "title": "90 天提升核心采购问题的候选进入率",
            "metric_key": "shortlist_rate",
            "target_value": 25,
            "due_at": "2026-12-31T23:59:00+08:00",
            "owner_user_id": 1,
            "question_plan_ids": [1],
            "model_keys": ["deepseek", "qwen"],
            "action_ids": [1],
            "period_days": 90,
            "batch_ids": [],
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["target_value"] == 25
    assert payload["owner_name"] == "企业管理员"
    assert payload["scope_snapshot"]["metric_contract"] == "evidence-gated-shortlist-rate/v1"
    assert payload["baseline_value"] is None
    assert payload["current_value"] is None
    assert payload["progress_percent"] is None

    read_back = results_client.get("/api/v1/workspaces/1/business-goal")
    assert read_back.status_code == 200
    assert read_back.json()["id"] == payload["id"]


def test_business_goal_rejects_owner_outside_workspace(results_client: TestClient) -> None:
    response = results_client.put(
        "/api/v1/workspaces/1/business-goal",
        json={
            "title": "提升核心采购问题的候选进入率",
            "target_value": 30,
            "due_at": "2026-12-31T23:59:00+08:00",
            "owner_user_id": 999,
            "question_plan_ids": [1],
            "model_keys": ["deepseek"],
            "action_ids": [1],
            "period_days": 30,
            "batch_ids": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "负责人不是当前工作区成员"


def test_roi_requires_real_cost_and_direct_revenue_then_calculates(
    results_client: TestClient,
) -> None:
    empty = results_client.get("/api/v1/workspaces/1/results-overview").json()["roi"]
    assert empty["status"] == "tracking"
    assert empty["roi_percent"] is None
    assert empty["decision"]["status"] == "setup_required"
    assert empty["readiness"]["ready_count"] == 1

    cost = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "action_id": 1,
            "metric_type": "content_cost",
            "amount": "1000.00",
            "currency": "CNY",
            "attribution_type": "not_applicable",
            "source_type": "finance",
            "source_label": "8 月费用报表",
            "source_reference": "FIN-2026-08",
            "evidence_note": "财务已核对的内容制作费用",
            "occurred_at": "2026-08-20T08:00:00Z",
            "idempotency_key": "cost-entry-0001",
        },
    )
    assert cost.status_code == 201
    duplicate = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "action_id": 1,
            "metric_type": "content_cost",
            "amount": "1000.00",
            "currency": "CNY",
            "attribution_type": "not_applicable",
            "source_type": "finance",
            "source_label": "8 月费用报表",
            "evidence_note": "重复提交不应重复入账",
            "occurred_at": "2026-08-20T08:00:00Z",
            "idempotency_key": "cost-entry-0001",
        },
    )
    assert duplicate.json()["status"] == "already_recorded"
    assisted = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "action_id": 1,
            "metric_type": "won_revenue",
            "amount": "5000.00",
            "currency": "CNY",
            "attribution_type": "assisted",
            "source_type": "crm",
            "source_label": "CRM 成交单 A",
            "evidence_note": "GEO 内容参与但不是直接来源",
            "occurred_at": "2026-08-21T08:00:00Z",
            "idempotency_key": "assisted-entry-1",
        },
    )
    assert assisted.status_code == 201
    partial = results_client.get("/api/v1/workspaces/1/results-overview").json()["roi"]
    assert partial["status"] == "tracking"
    assert partial["assisted_revenue_minor"] == 500000

    direct = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "action_id": 1,
            "metric_type": "won_revenue",
            "amount": "3000.00",
            "currency": "CNY",
            "attribution_type": "direct",
            "source_type": "crm",
            "source_label": "CRM 成交单 B",
            "source_reference": "CRM-DEAL-B",
            "evidence_note": "首触来源为 AI 引荐并完成成交",
            "occurred_at": "2026-08-22T08:00:00Z",
            "idempotency_key": "direct-entry-001",
        },
    )
    assert direct.status_code == 201
    roi = results_client.get("/api/v1/workspaces/1/results-overview").json()["roi"]
    assert roi["status"] == "calculable"
    assert roi["total_cost_minor"] == 100000
    assert roi["direct_revenue_minor"] == 300000
    assert roi["roi_percent"] == 200.0
    assert roi["decision"]["status"] == "ready_for_review"
    assert roi["action_portfolio"][0]["recommendation"] == "进入经营评审"


def test_direct_revenue_requires_action_and_auditable_reference(
    results_client: TestClient,
) -> None:
    response = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "metric_type": "won_revenue",
            "amount": "3000.00",
            "currency": "CNY",
            "attribution_type": "direct",
            "source_type": "crm",
            "source_label": "CRM 成交单",
            "evidence_note": "没有关联行动和凭证编号",
            "occurred_at": "2026-08-22T08:00:00Z",
            "idempotency_key": "unproven-direct-1",
        },
    )
    assert response.status_code == 422


def test_roi_returns_previous_period_comparison_and_real_trend(
    results_client: TestClient,
) -> None:
    now = datetime.now(timezone.utc)
    rows = [
        ("previous-cost", "content_cost", "2000.00", now - timedelta(days=35), "finance", "not_applicable"),
        ("previous-revenue", "won_revenue", "3000.00", now - timedelta(days=34), "crm", "direct"),
        ("current-cost", "content_cost", "1000.00", now - timedelta(days=5), "finance", "not_applicable"),
        ("current-revenue", "won_revenue", "3000.00", now - timedelta(days=4), "crm", "direct"),
    ]
    for key, metric_type, amount, occurred_at, source_type, attribution_type in rows:
        response = results_client.post(
            "/api/v1/workspaces/1/business-metrics",
            json={
                "action_id": 1,
                "metric_type": metric_type,
                "amount": amount,
                "currency": "CNY",
                "attribution_type": attribution_type,
                "source_type": source_type,
                "source_label": key,
                "source_reference": f"REF-{key}",
                "evidence_note": "用于验证真实周期对比与趋势聚合",
                "occurred_at": occurred_at.isoformat(),
                "idempotency_key": key,
            },
        )
        assert response.status_code == 201

    roi = results_client.get(
        "/api/v1/workspaces/1/results-overview?period_days=30"
    ).json()["roi"]
    assert roi["roi_percent"] == 200.0
    assert roi["comparison"]["previous"]["roi_percent"] == 50.0
    assert roi["comparison"]["cost_change_percent"] == -50.0
    assert roi["comparison"]["revenue_change_percent"] == 0.0
    assert roi["comparison"]["net_change_percent"] == 100.0
    assert roi["comparison"]["roi_change_percentage_points"] == 150.0
    assert roi["trend"][-1]["cost_minor"] == 100000
    assert roi["trend"][-1]["revenue_minor"] == 300000
    assert roi["action_markers"][0]["action_id"] == 1
    assert roi["action_portfolio"][0]["roi_percent"] == 200.0


def test_pipeline_value_is_visible_but_never_counted_as_realized_roi(
    results_client: TestClient,
) -> None:
    response = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "action_id": 1,
            "metric_type": "pipeline_value",
            "amount": "8000.00",
            "currency": "CNY",
            "attribution_type": "assisted",
            "source_type": "crm",
            "source_label": "CRM 商机管道",
            "source_reference": "CRM-OPP-8",
            "evidence_note": "已进入商机，但尚未成交",
            "occurred_at": "2026-08-22T08:00:00Z",
            "idempotency_key": "pipeline-entry-1",
        },
    )
    assert response.status_code == 201
    roi = results_client.get("/api/v1/workspaces/1/results-overview").json()["roi"]
    assert roi["pipeline_value_minor"] == 800000
    assert roi["direct_revenue_minor"] == 0
    assert roi["roi_percent"] is None


def test_reversing_direct_revenue_removes_it_from_realized_return(
    results_client: TestClient,
) -> None:
    created = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "action_id": 1,
            "metric_type": "won_revenue",
            "amount": "1200.00",
            "currency": "CNY",
            "attribution_type": "direct",
            "source_type": "crm",
            "source_label": "CRM 成交单 C",
            "source_reference": "CRM-DEAL-C",
            "evidence_note": "后续确认这笔成交需要冲销",
            "occurred_at": "2026-08-22T08:00:00Z",
            "idempotency_key": "direct-reverse-source-1",
        },
    )
    entry_id = created.json()["id"]
    reversed_response = results_client.post(
        f"/api/v1/workspaces/1/business-metrics/{entry_id}/reverse",
        json={"reason": "成交后续取消", "idempotency_key": "direct-reverse-row-1"},
    )
    assert reversed_response.status_code == 201
    roi = results_client.get("/api/v1/workspaces/1/results-overview").json()["roi"]
    assert roi["direct_revenue_minor"] == 0
    assert roi["roi_percent"] is None


def test_business_entry_can_be_reversed_without_deleting_original(
    results_client: TestClient,
) -> None:
    created = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "metric_type": "qualified_lead",
            "quantity": 4,
            "attribution_type": "direct",
            "source_type": "crm",
            "source_label": "CRM 线索报表",
            "evidence_note": "核对后发现口径重复",
            "occurred_at": "2026-08-22T08:00:00Z",
            "idempotency_key": "lead-entry-0001",
        },
    )
    entry_id = created.json()["id"]
    reversed_response = results_client.post(
        f"/api/v1/workspaces/1/business-metrics/{entry_id}/reverse",
        json={"reason": "与另一条 CRM 记录重复", "idempotency_key": "reverse-lead-001"},
    )
    assert reversed_response.status_code == 201
    overview = results_client.get("/api/v1/workspaces/1/results-overview").json()["roi"]
    assert overview["quantities"]["qualified_lead"] == 0
    assert overview["entry_count"] == 2
    sessions = results_client.app.state.results_sessions
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(GeoBusinessMetricEntry)) == 2


def test_global_viewer_cannot_write_business_metrics(results_client: TestClient) -> None:
    results_client.app.state.results_user.role = "viewer"
    sessions = results_client.app.state.results_sessions
    with sessions() as db:
        membership = db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == 1,
                WorkspaceMembership.user_id == 1,
            )
        )
        assert membership is not None
        membership.role = "viewer"
        db.add(membership)
        db.commit()
    response = results_client.post(
        "/api/v1/workspaces/1/business-metrics",
        json={
            "metric_type": "qualified_lead",
            "quantity": 1,
            "attribution_type": "direct",
            "source_type": "crm",
            "source_label": "CRM",
            "evidence_note": "只读用户不应写入",
            "occurred_at": "2026-08-22T08:00:00Z",
            "idempotency_key": "viewer-write-001",
        },
    )
    assert response.status_code == 403


def test_roi_csv_preflight_import_idempotency_error_report_and_reversal(
    results_client: TestClient,
) -> None:
    csv_text = """record_id,occurred_at,metric_type,amount,quantity,currency,action_id,attribution_type,source_type,source_reference,source_label,evidence_note
cost-001,2026-08-22T08:00:00Z,content_cost,100.00,,CNY,1,not_applicable,manual_import,FIN-001,8月成本表,行动1内容制作成本
deal-001,2026-08-22T09:00:00Z,won_revenue,500.00,,CNY,1,direct,crm,,CRM成交表,直接成交但缺少凭证
cost-001,2026-08-22T10:00:00Z,qualified_lead,,2,,1,direct,crm,LEAD-2,CRM线索表,文件内重复编号
formula-001,2026-08-22T11:00:00Z,qualified_lead,,2,,1,direct,crm,LEAD-3,=HYPERLINK(""https://bad.example""),疑似公式注入
"""
    preflight = results_client.post(
        "/api/v1/workspaces/1/business-metric-imports/preflight",
        json={"file_name": "roi-aug.csv", "csv_text": csv_text},
    )
    assert preflight.status_code == 201, preflight.text
    batch = preflight.json()
    assert batch["total_rows"] == 4
    assert batch["valid_rows"] == 1
    assert batch["error_rows"] == 2
    assert batch["duplicate_rows"] == 1
    assert any(
        error["code"] == "formula_injection"
        for row in batch["rows"]
        for error in row["errors"]
    )

    report = results_client.get(
        f"/api/v1/workspaces/1/business-metric-imports/{batch['id']}/errors.csv"
    )
    assert report.status_code == 200
    assert "formula_injection" in report.text
    assert "duplicate" in report.text

    confirmed = results_client.post(
        f"/api/v1/workspaces/1/business-metric-imports/{batch['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["imported_rows"] == 1
    repeated = results_client.post(
        "/api/v1/workspaces/1/business-metric-imports/preflight",
        json={"file_name": "roi-aug-again.csv", "csv_text": csv_text},
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == batch["id"]
    assert repeated.json()["imported_rows"] == 1
    with results_client.app.state.results_sessions() as db:
        imported = list(
            db.scalars(
                select(GeoBusinessMetricEntry).where(
                    GeoBusinessMetricEntry.source_record_id == "cost-001"
                )
            )
        )
        assert len(imported) == 1

    reversed_batch = results_client.post(
        f"/api/v1/workspaces/1/business-metric-imports/{batch['id']}/reverse",
        json={"reason": "测试数据批量撤销"},
    )
    assert reversed_batch.status_code == 200, reversed_batch.text
    assert reversed_batch.json()["status"] == "reversed"
    overview = results_client.get("/api/v1/workspaces/1/results-overview").json()["roi"]
    assert overview["total_cost_minor"] == 0


def test_roi_csv_template_is_downloadable(results_client: TestClient) -> None:
    response = results_client.get(
        "/api/v1/workspaces/1/business-metric-imports/template"
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "record_id" in response.text
    assert "metric_type" in response.text
