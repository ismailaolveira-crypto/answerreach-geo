from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.session import Base
from app.models import QueueJob
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoActionOpportunity,
    GeoEvidence,
    GeoObservationBatch,
    GeoObservationRun,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.services.codex_agent_runtime import CodexTurnResult
from app.v1 import opportunity_agent
from app.v1 import agent_run_routes, routes
from app.v1.schemas import ActionOpportunityDiscoverRequest


def test_runtime_selection_rejects_effort_not_supported_by_model() -> None:
    diagnostic = {
        "default_model": "gpt-fast",
        "available_models": ["gpt-fast"],
        "model_options": [
            {
                "id": "gpt-fast",
                "default_reasoning_effort": "low",
                "supported_reasoning_efforts": ["low", "medium"],
            }
        ],
    }

    with pytest.raises(HTTPException) as exc_info:
        agent_run_routes._resolve_codex_execution(
            diagnostic,
            requested_model="gpt-fast",
            requested_reasoning_effort="ultra",
        )

    assert exc_info.value.status_code == 422
    assert "does not support" in str(exc_info.value.detail)


def _seed(db: Session) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            Company(id=1, name="测试公司"),
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="agent-opportunity-test",
                brand_name="春秋元泉",
                brand_aliases=[],
                website_url="https://brand.example",
            ),
            GeoQuestionPlan(
                id=1,
                workspace_id=1,
                question_text="企业级大模型治理平台怎么选？",
                journey_stage="consideration",
                role="technical_lead",
                topic_tags=[],
                importance=5,
                is_brand_query=False,
                active=True,
                status="active",
                source_type="manual",
                source_evidence={},
                template_variables=[],
            ),
            GeoObservationBatch(
                id=1,
                workspace_id=1,
                status="completed",
                source_type="official_api",
                provider_count=1,
                question_count=1,
                repeat_count=1,
                total_tasks=1,
                completed_tasks=1,
                failed_tasks=0,
                configuration={},
                started_at=now,
                completed_at=now,
            ),
            GeoObservationRun(
                id=1,
                workspace_id=1,
                adapter_key="official_api",
                status="completed",
                request_context={},
                started_at=now,
                completed_at=now,
            ),
        ]
    )
    db.flush()
    db.add(
        GeoEvidence(
            id=1,
            workspace_id=1,
            run_id=1,
            question_plan_id=1,
            model_key="deepseek",
            model_label="DeepSeek",
            prompt_version="v1",
            sample_mode="authorized_api",
            evidence_level="auditable",
            collection_method="official_api_web_search",
            evidence_kind="provider_web_search",
            is_real_provider_evidence=True,
            brand_status="absent",
            competitor_positions=[{"name": "竞品甲", "position": 1}],
            answer_text="竞品甲的回答介绍了企业选型指标，未提到春秋元泉。",
            answer_hash="1" * 64,
            source_items=[
                {
                    "url": "https://www.zhihu.com/question/1/answer/2",
                    "title": "企业选型回答",
                }
            ],
            sampling_environment={"search_verified": True, "search_event_count": 1},
            raw_artifact_uri="file:///private/evidence/1.json",
            captured_at=now,
        )
    )
    db.flush()
    db.add(
        GeoObservationTask(
            batch_id=1,
            workspace_id=1,
            run_id=1,
            evidence_id=1,
            provider_key="deepseek_web_search",
            provider_label="DeepSeek",
            model_key="deepseek",
            model_label="DeepSeek",
            question_plan_id=1,
            question_text_snapshot="企业级大模型治理平台怎么选？",
            sample_key="deepseek:1:1",
            repeat_index=1,
            repeat_count=1,
            status="completed",
            completed_at=now,
        )
    )
    db.commit()


class FakeRuntime:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def run_structured(self, **kwargs) -> CodexTurnResult:
        kwargs["on_started"]("thread-test", "turn-test")
        return CodexTurnResult(
            thread_id="thread-test",
            turn_id="turn-test",
            final_response=json.dumps(self.payload, ensure_ascii=False),
        )


def _result(evidence_ids: list[int]) -> dict:
    return {
        "analysis_summary": "建议在可运营信源补齐企业选型内容。",
        "opportunities": [
            {
                "question_plan_id": 1,
                "opportunity_type": "competitor_gap",
                "title": "在知乎补齐企业治理平台选型回答",
                "summary": "当前回答已出现竞品选型信息，但没有春秋元泉的可核验答案。",
                "priority_label": "high",
                "priority_score": 88,
                "confidence": 0.86,
                "evidence_ids": evidence_ids,
                "recommended_asset_type": "知乎深度回答",
                "recommended_platforms": ["zhihu"],
                "source_strategy": "direct_operable_source",
                "target_source_url": "https://www.zhihu.com/question/1/answer/2",
                "missing_content": ["选型判断标准", "产品能力边界"],
                "competitor_content_patterns": ["先给选型维度，再说明适用场景"],
                "rationale": "信源可运营，且竞品内容规律和品牌缺口都有同一条证据支持。",
                "uncertainties": ["品牌功能声明仍需使用已核验事实"],
            }
        ],
        "no_action_reasons": [],
    }


def test_context_build_does_not_materialize_rule_opportunities() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        context = opportunity_agent.build_opportunity_context(
            db, 1, batch_id=1, model_keys=["deepseek"]
        )
        assert context["evidence"][0]["evidence_id"] == 1
        assert db.scalar(select(GeoActionOpportunity)) is None


def test_successful_codex_run_materializes_validated_opportunity(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(opportunity_agent, "ARTIFACT_ROOT", tmp_path)
    with Session(engine) as db:
        _seed(db)
        context = opportunity_agent.build_opportunity_context(
            db, 1, batch_id=1, model_keys=["deepseek"]
        )
        job = QueueJob(
            id=1,
            job_type="geo_opportunity.discover",
            status="running",
            priority=25,
            attempts=1,
            max_attempts=1,
            scheduled_at=datetime.now(UTC),
            payload_json={
                "workspace_id": 1,
                "batch_id": 1,
                "model_keys": ["deepseek"],
                "question_plan_ids": [],
                "input_fingerprint": context["input_fingerprint"],
                "stage": "queued",
            },
        )
        db.add(job)
        db.commit()

        result = opportunity_agent.execute_opportunity_analysis(
            db, job, runtime=FakeRuntime(_result([1]))
        )
        opportunity = db.scalar(select(GeoActionOpportunity))

        assert result["result_count"] == 1
        assert opportunity is not None
        assert opportunity.rule_version == opportunity_agent.AGENT_RULE_VERSION
        assert opportunity.scope_snapshot["discovery_job_id"] == 1
        assert opportunity.scope_snapshot["codex_thread_id"] == "thread-test"
        assert opportunity.scope_snapshot["question"] == "企业级大模型治理平台怎么选？"


def test_same_recommendation_in_a_new_batch_updates_instead_of_duplicating() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        context = opportunity_agent.build_opportunity_context(
            db, 1, batch_id=1, model_keys=["deepseek"]
        )
        job = SimpleNamespace(id=1, payload_json={"codex_thread_id": "thread-1"})
        first = opportunity_agent.materialize_agent_opportunities(
            db, job=job, context=context, parsed=_result([1])
        )
        next_context = json.loads(json.dumps(context))
        next_context["scope"]["batch_id"] = 2
        next_context["input_fingerprint"] = "2" * 64
        second = opportunity_agent.materialize_agent_opportunities(
            db, job=job, context=next_context, parsed=_result([1])
        )
        db.commit()

        assert first[0].id == second[0].id
        assert db.scalars(select(GeoActionOpportunity)).all() == [first[0]]
        assert first[0].latest_seen_batch_id == 2


def test_out_of_scope_agent_evidence_creates_no_opportunity(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(opportunity_agent, "ARTIFACT_ROOT", tmp_path)
    with Session(engine) as db:
        _seed(db)
        context = opportunity_agent.build_opportunity_context(db, 1, batch_id=1)
        job = QueueJob(
            id=1,
            job_type="geo_opportunity.discover",
            status="running",
            priority=25,
            attempts=1,
            max_attempts=1,
            scheduled_at=datetime.now(UTC),
            payload_json={
                "workspace_id": 1,
                "batch_id": 1,
                "model_keys": [],
                "question_plan_ids": [],
                "input_fingerprint": context["input_fingerprint"],
            },
        )
        db.add(job)
        db.commit()

        with pytest.raises(ValueError, match="outside the selected scope"):
            opportunity_agent.execute_opportunity_analysis(
                db, job, runtime=FakeRuntime(_result([999]))
            )
        assert db.scalar(select(GeoActionOpportunity)) is None


def test_route_queues_codex_before_any_opportunity_is_visible(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        db.add(
            GeoActionOpportunity(
                workspace_id=1,
                fingerprint="legacy-rule-row",
                opportunity_type="brand_absent",
                title="旧规则机会",
                summary="仅用于验证历史行不再冒充 Codex 结果。",
                priority_score=80,
                priority_label="high",
                evidence_strength=1,
                recommended_asset_type="article",
                recommended_platforms=["zhihu"],
                scope_snapshot={"batch_id": 1, "model_keys": ["deepseek"]},
                rule_version="opportunity.v2",
                status="open",
                first_seen_batch_id=1,
                latest_seen_batch_id=1,
            )
        )
        db.commit()
        user = SimpleNamespace(id=1, role="super_admin", company_id=1)
        monkeypatch.setattr(
            agent_run_routes,
            "diagnose_local_codex",
            lambda: {
                "ready": True,
                "default_model": "gpt-test",
                "available_models": ["gpt-test"],
            },
        )
        monkeypatch.setattr(agent_run_routes, "invalidate_local_codex_diagnostic_cache", lambda: None)
        monkeypatch.setattr(routes, "_assert_agent_capacity", lambda *_args, **_kwargs: None)

        run = routes.discover_action_opportunities(
            1,
            ActionOpportunityDiscoverRequest(
                batch_id=1,
                model_keys=["deepseek"],
                question_plan_ids=[],
                codex_model="gpt-test",
                reasoning_effort="low",
            ),
            db,
            user,
        )
        visible = routes.list_action_opportunities(
            1,
            status=None,
            batch_id=1,
            model_key="deepseek",
            question_plan_id=None,
            include_legacy=False,
            db=db,
            user=user,
        )
        legacy = routes.list_action_opportunities(
            1,
            status=None,
            batch_id=1,
            model_key="deepseek",
            question_plan_id=None,
            include_legacy=True,
            db=db,
            user=user,
        )

        assert run["status"] == "queued"
        assert run["model"] == "gpt-test"
        assert run["reasoning_effort"] == "low"
        assert run["result_count"] == 0
        assert visible == []
        assert [row["title"] for row in legacy] == ["旧规则机会"]
