from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

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
from app.v1 import routes, website_gap_agent
from app.v1.schemas import WebsiteGapAnalysisRequest


def _seed(db: Session) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            Company(id=1, name="测试公司"),
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="website-gap-test",
                brand_name="春秋元泉",
                brand_aliases=[],
                website_url="https://brand.example/",
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
                provider_count=2,
                question_count=1,
                repeat_count=1,
                total_tasks=2,
                completed_tasks=2,
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
    db.add_all(
        [
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
                brand_status="cited",
                competitor_positions=[],
                answer_text="回答引用了春秋元泉官网的产品说明。",
                answer_hash="1" * 64,
                source_items=[{"url": "https://brand.example/product", "title": "产品说明"}],
                sampling_environment={"search_verified": True, "search_event_count": 1},
                raw_artifact_uri="file:///private/evidence/1.json",
                captured_at=now,
            ),
            GeoEvidence(
                id=2,
                workspace_id=1,
                run_id=1,
                question_plan_id=1,
                model_key="qianwen",
                model_label="通义千问",
                prompt_version="v1",
                sample_mode="authorized_api",
                evidence_level="auditable",
                collection_method="official_api_web_search",
                evidence_kind="provider_web_search",
                is_real_provider_evidence=True,
                brand_status="absent",
                competitor_positions=[{"name": "竞品甲", "position": 1}],
                answer_text="竞品甲提供了私有化部署边界、成本项和验收流程。",
                answer_hash="2" * 64,
                source_items=[{"url": "https://competitor.example/guide", "title": "私有化部署指南"}],
                sampling_environment={"search_verified": True, "search_event_count": 1},
                raw_artifact_uri="file:///private/evidence/2.json",
                captured_at=now,
            ),
        ]
    )
    db.flush()
    for evidence_id, model_key, model_label in [
        (1, "deepseek", "DeepSeek"),
        (2, "qianwen", "通义千问"),
    ]:
        db.add(
            GeoObservationTask(
                batch_id=1,
                workspace_id=1,
                run_id=1,
                evidence_id=evidence_id,
                provider_key=f"{model_key}_web_search",
                provider_label=model_label,
                model_key=model_key,
                model_label=model_label,
                question_plan_id=1,
                question_text_snapshot="企业级大模型治理平台怎么选？",
                sample_key=f"{model_key}:1:1",
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
        self.developer_instructions = ""

    def run_structured(self, **kwargs) -> CodexTurnResult:
        self.developer_instructions = kwargs["developer_instructions"]
        kwargs["on_started"]("thread-website", "turn-website")
        return CodexTurnResult(
            thread_id="thread-website",
            turn_id="turn-website",
            final_response=json.dumps(self.payload, ensure_ascii=False),
        )


def _result(context: dict) -> dict:
    return {
        "skill_contract": context["skill_contract"],
        "analysis_summary": "官网只在 DeepSeek 回答中被引用，通义千问更多采用了竞品的部署与验收内容。",
        "confidence": 0.82,
        "official_performance": {
            "interpretation": "2 条有效回答中官网被引用 1 次。",
            "content_use_status": "not_measurable",
        },
        "competitor_content_gaps": [
            {
                "theme": "私有化部署与验收",
                "why_it_matters": "竞品在同一问题的回答中提供了可执行流程。",
                "evidence_ids": [2],
                "affected_models": ["qianwen"],
                "affected_question_plan_ids": [1],
                "source_urls": ["https://competitor.example/guide"],
            }
        ],
        "recommendations": [
            {
                "priority": "medium",
                "title": "补齐私有化部署与验收页",
                "target_page": "/solutions/private-deployment",
                "required_content": ["部署前置条件", "验收步骤", "能力边界"],
                "reason": "同范围竞品回答已使用这类内容。",
                "evidence_ids": [2],
                "affected_models": ["qianwen"],
                "affected_question_plan_ids": [1],
                "source_urls": ["https://competitor.example/guide"],
            }
        ],
        "limitations": ["没有官网段落快照，因此不评估内容采用深度。"],
    }


def test_context_freezes_exact_scope_and_uses_deterministic_citation_counts() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        context = website_gap_agent.build_website_gap_context(db, 1, batch_id=1)

    assert context["scope_manifest"]["resolved_model_keys"] == ["deepseek", "qianwen"]
    assert context["scope_manifest"]["eligible_evidence_ids"] == [1, 2]
    assert context["deterministic_metrics"]["official_cited_answer_count"] == 1
    assert context["deterministic_metrics"]["official_citation_rate"] == 0.5


def test_forced_skill_is_injected_and_persisted_without_new_schema(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(website_gap_agent, "ARTIFACT_ROOT", tmp_path)
    with Session(engine) as db:
        _seed(db)
        context = website_gap_agent.build_website_gap_context(db, 1, batch_id=1)
        job = QueueJob(
            id=1,
            job_type=website_gap_agent.WEBSITE_GAP_JOB_TYPE,
            status="running",
            priority=26,
            attempts=1,
            max_attempts=1,
            scheduled_at=datetime.now(UTC),
            payload_json={
                "workspace_id": 1,
                "batch_id": 1,
                "model_keys": [],
                "question_plan_ids": [],
                "input_fingerprint": context["input_fingerprint"],
                "skill_name": context["skill_contract"]["name"],
                "skill_sha256": context["skill_contract"]["sha256"],
            },
        )
        db.add(job)
        db.commit()
        runtime = FakeRuntime(_result(context))

        result = website_gap_agent.execute_website_gap_analysis(db, job, runtime=runtime)
        opportunity = db.scalar(select(GeoActionOpportunity))
        persisted_payload = dict(job.payload_json or {})
        user = SimpleNamespace(id=1, role="super_admin", company_id=1)
        exact_scope_rows = routes.list_action_opportunities(
            1,
            status=None,
            batch_id=1,
            model_key=None,
            question_plan_id=None,
            include_legacy=False,
            db=db,
            user=user,
        )
        different_scope_rows = routes.list_action_opportunities(
            1,
            status=None,
            batch_id=1,
            model_key="qianwen",
            question_plan_id=None,
            include_legacy=False,
            db=db,
            user=user,
        )

    assert result["result_count"] == 1
    assert opportunity is None
    assert persisted_payload["recommendation_count"] == 1
    assert persisted_payload["recommendations"][0]["title"] == "补齐私有化部署与验收页"
    assert "MANDATORY_SKILL_CONTRACT" in runtime.developer_instructions
    assert context["skill_contract"]["sha256"] in runtime.developer_instructions
    assert exact_scope_rows == []
    assert different_scope_rows == []


def test_result_without_skill_acknowledgement_is_rejected() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        context = website_gap_agent.build_website_gap_context(db, 1, batch_id=1)
        result = _result(context)
        result["skill_contract"] = {"name": "wrong", "sha256": "0" * 64}
        with pytest.raises(ValueError, match="mandatory website analysis Skill"):
            website_gap_agent.validate_result(context, result)


def test_route_queues_selected_scope_with_skill_hash(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        monkeypatch.setattr(
            routes,
            "diagnose_local_codex",
            lambda: {"ready": True, "default_model": "gpt-test", "available_models": ["gpt-test"]},
        )
        monkeypatch.setattr(routes, "invalidate_local_codex_diagnostic_cache", lambda: None)
        monkeypatch.setattr(routes, "_assert_agent_capacity", lambda *_args, **_kwargs: None)
        user = SimpleNamespace(id=1, role="super_admin", company_id=1)

        run = routes.create_website_gap_analysis(
            1,
            WebsiteGapAnalysisRequest(
                batch_id=1,
                model_keys=["qianwen"],
                question_plan_ids=[1],
                codex_model="gpt-test",
                reasoning_effort="high",
            ),
            db,
            user,
        )
        job = db.get(QueueJob, run["job_id"])

    assert run["status"] == "queued"
    assert run["model_keys"] == ["qianwen"]
    assert run["question_plan_ids"] == [1]
    assert run["model"] == "gpt-test"
    assert run["reasoning_effort"] == "high"
    assert job is not None
    assert job.payload_json["skill_name"] == website_gap_agent.SKILL_NAME
    assert job.payload_json["reasoning_effort"] == "high"
    assert len(job.payload_json["skill_sha256"]) == 64
