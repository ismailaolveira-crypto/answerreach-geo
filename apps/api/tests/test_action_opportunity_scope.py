from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.session import Base
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
from app.v1.action_opportunities import discover_opportunities, valid_action_evidence
from app.v1.routes import get_action_opportunity_scope


def _evidence(
    evidence_id: int,
    *,
    model_key: str,
    search_verified: bool,
    search_event_count: int,
) -> GeoEvidence:
    return GeoEvidence(
        id=evidence_id,
        workspace_id=1,
        run_id=1,
        question_plan_id=1,
        model_key=model_key,
        model_label=model_key,
        prompt_version="v1",
        sample_mode="authorized_api",
        evidence_level="auditable",
        collection_method="official_api_web_search",
        evidence_kind="provider_web_search",
        is_real_provider_evidence=True,
        brand_status="absent",
        competitor_positions=[],
        answer_text=f"真实回答 {evidence_id}",
        answer_hash=f"{evidence_id:064x}",
        source_items=[{"url": f"https://example.com/source/{evidence_id}"}],
        sampling_environment={
            "search_verified": search_verified,
            "search_event_count": search_event_count,
        },
        raw_artifact_uri=f"file:///private/evidence/{evidence_id}.json",
        captured_at=datetime.now(timezone.utc),
    )


def _seed(db: Session) -> tuple[GeoWorkspace, GeoEvidence, GeoEvidence]:
    now = datetime.now(timezone.utc)
    workspace = GeoWorkspace(
        id=1,
        company_id=1,
        slug="scope-test",
        brand_name="春秋元泉",
        brand_aliases=[],
        website_url="https://example.com",
    )
    question = GeoQuestionPlan(
        id=1,
        workspace_id=1,
        question_text="Token 统一管控平台哪家好？",
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
    )
    batch = GeoObservationBatch(
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
    )
    run = GeoObservationRun(
        id=1,
        workspace_id=1,
        adapter_key="official_api",
        status="completed",
        request_context={},
        started_at=now,
        completed_at=now,
    )
    valid = _evidence(1, model_key="deepseek", search_verified=True, search_event_count=1)
    missing_search = _evidence(
        2,
        model_key="qianwen",
        search_verified=False,
        search_event_count=0,
    )
    db.add_all([Company(id=1, name="测试公司"), workspace, question, batch, run, valid, missing_search])
    db.flush()
    db.add_all(
        [
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
                question_text_snapshot=question.question_text,
                sample_key="deepseek:1:1",
                repeat_index=1,
                repeat_count=1,
                status="completed",
                completed_at=now,
            ),
            GeoObservationTask(
                batch_id=1,
                workspace_id=1,
                run_id=1,
                evidence_id=2,
                provider_key="qwen_web_search",
                provider_label="通义千问",
                model_key="qianwen",
                model_label="通义千问",
                question_plan_id=1,
                question_text_snapshot=question.question_text,
                sample_key="qianwen:1:1",
                repeat_index=1,
                repeat_count=1,
                status="completed",
                completed_at=now,
            ),
        ]
    )
    db.commit()
    return workspace, valid, missing_search


def test_discovery_requires_search_event_and_respects_model_scope() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        workspace, valid, missing_search = _seed(db)
        assert valid_action_evidence(valid) is True
        assert valid_action_evidence(missing_search) is False

        rows = discover_opportunities(
            db,
            workspace,
            batch_id=1,
            question_plan_ids=[1],
            model_keys=["deepseek"],
        )
        assert len(rows) == 1
        assert rows[0].scope_snapshot["model_keys"] == ["deepseek"]
        assert rows[0].scope_snapshot["evidence_count"] == 1

        rows[0].status = "selected"
        db.commit()
        assert discover_opportunities(
            db,
            workspace,
            batch_id=1,
            question_plan_ids=[1],
            model_keys=["qianwen"],
        ) == []
        selected = db.scalar(select(GeoActionOpportunity).where(GeoActionOpportunity.id == rows[0].id))
        assert selected is not None
        assert selected.status == "selected"


def test_scope_exposes_only_batches_and_models_with_complete_evidence_gate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        result = get_action_opportunity_scope(
            1,
            db=db,
            user=SimpleNamespace(id=1, company_id=1, role="company_admin"),
        )
        assert result["latest_batch_id"] == 1
        assert result["batches"][0]["eligible_evidence_count"] == 1
        assert result["batches"][0]["model_keys"] == ["deepseek"]
        assert result["models"] == [{"key": "deepseek", "label": "DeepSeek"}]
        assert result["evidence_gate"].endswith("search_event+source_url+raw_artifact")


def test_scope_returns_at_most_twelve_latest_eligible_batches() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        now = datetime.now(timezone.utc)
        for batch_id in range(2, 15):
            evidence_id = 100 + batch_id
            evidence = _evidence(
                evidence_id,
                model_key="deepseek",
                search_verified=True,
                search_event_count=1,
            )
            db.add_all(
                [
                    GeoObservationBatch(
                        id=batch_id,
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
                    evidence,
                ]
            )
            db.flush()
            db.add(
                GeoObservationTask(
                    batch_id=batch_id,
                    workspace_id=1,
                    run_id=1,
                    evidence_id=evidence_id,
                    provider_key="deepseek_web_search",
                    provider_label="DeepSeek",
                    model_key="deepseek",
                    model_label="DeepSeek",
                    question_plan_id=1,
                    question_text_snapshot="Token 统一管控平台哪家好？",
                    sample_key=f"deepseek:1:{batch_id}",
                    repeat_index=1,
                    repeat_count=1,
                    status="completed",
                    completed_at=now,
                )
            )
        db.commit()

        result = get_action_opportunity_scope(
            1,
            db=db,
            user=SimpleNamespace(id=1, company_id=1, role="company_admin"),
        )
        assert len(result["batches"]) == 12
        assert [batch["id"] for batch in result["batches"]] == list(range(14, 2, -1))
