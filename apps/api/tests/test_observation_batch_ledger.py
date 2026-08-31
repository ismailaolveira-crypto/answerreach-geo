from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.session import Base
from app.models.company import Company
from app.models.cleanroom_v1 import (
    GeoObservationBatch,
    GeoObservationTask,
    GeoQuestionPlan,
    GeoWorkspace,
)
from app.models.user import User
from app.services.workspace_access import add_membership
from app.v1.observation_routes import (
    get_latest_provider_web_search_batch,
    get_provider_web_search_batch,
    list_provider_web_search_batches,
)
from app.v1.insight_routes import get_decision_map
from app.v1.schemas import (
    OfficialApiObservationBatchListRead,
    OfficialApiObservationBatchRead,
)


def _seed_ledger(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            Company(id=1, name="测试公司"),
            User(id=1, company_id=1, name="测试管理员", email="ledger@example.com", role="company_admin"),
            GeoWorkspace(
                id=1,
                company_id=1,
                slug="ledger-history",
                brand_name="春秋元泉",
                brand_aliases=[],
                website_url="https://example.com",
            ),
            GeoQuestionPlan(
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
            ),
            GeoObservationBatch(
                id=7,
                workspace_id=1,
                queue_job_id=None,
                source_type="legacy_import",
                status="completed",
                provider_count=2,
                question_count=1,
                repeat_count=1,
                total_tasks=2,
                completed_tasks=1,
                failed_tasks=1,
                configuration={},
                started_at=now,
                completed_at=now,
            ),
            GeoObservationBatch(
                id=8,
                workspace_id=1,
                queue_job_id=None,
                source_type="official_api",
                status="running",
                provider_count=1,
                question_count=1,
                repeat_count=1,
                total_tasks=1,
                completed_tasks=0,
                failed_tasks=0,
                configuration={},
                started_at=now,
            ),
        ]
    )
    db.flush()
    add_membership(db, workspace_id=1, user_id=1, role="owner")
    db.add_all(
        [
            GeoObservationTask(
                id=71,
                batch_id=7,
                workspace_id=1,
                provider_key="deepseek_web_search",
                provider_label="DeepSeek",
                model_key="deepseek",
                model_label="DeepSeek",
                question_plan_id=1,
                question_text_snapshot="Token 统一管控平台哪家好？",
                sample_key="deepseek:1",
                repeat_index=1,
                repeat_count=1,
                status="completed",
                attempt_count=1,
                started_at=now,
                completed_at=now,
            ),
            GeoObservationTask(
                id=72,
                batch_id=7,
                workspace_id=1,
                provider_key="qwen_web_search",
                provider_label="通义千问",
                model_key="qianwen",
                model_label="通义千问",
                question_plan_id=1,
                question_text_snapshot="Token 统一管控平台哪家好？",
                sample_key="qianwen:1",
                repeat_index=1,
                repeat_count=1,
                status="failed",
                attempt_count=1,
                error_code="provider_timeout",
                error_detail="模型响应超时",
                started_at=now,
                completed_at=now,
            ),
            GeoObservationTask(
                id=81,
                batch_id=8,
                workspace_id=1,
                provider_key="deepseek_web_search",
                provider_label="DeepSeek",
                model_key="deepseek",
                model_label="DeepSeek",
                question_plan_id=1,
                question_text_snapshot="Token 统一管控平台哪家好？",
                sample_key="deepseek:running",
                repeat_index=1,
                repeat_count=1,
                status="running",
                attempt_count=1,
                started_at=now,
            ),
        ]
    )
    db.commit()


def test_batch_history_uses_canonical_ledger_ids_without_queue_jobs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed_ledger(db)
        user = SimpleNamespace(id=1, company_id=1, role="company_admin")

        result = list_provider_web_search_batches(
            1,
            page=1,
            page_size=20,
            db=db,
            user=user,
        )
        validated = OfficialApiObservationBatchListRead.model_validate(result)

        assert validated.pagination.total == 2
        assert [item.batch_id for item in validated.items] == [8, 7]
        assert validated.items[0].status == "running"
        assert validated.items[1].status == "partial"
        assert validated.items[1].source_type == "legacy_import"


def test_batch_detail_and_latest_share_the_same_ledger_identifier() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed_ledger(db)
        user = SimpleNamespace(id=1, company_id=1, role="company_admin")

        latest = OfficialApiObservationBatchRead.model_validate(
            get_latest_provider_web_search_batch(1, db=db, user=user)
        )
        detail = OfficialApiObservationBatchRead.model_validate(
            get_provider_web_search_batch(
                1,
                7,
                task_page=1,
                task_page_size=125,
                db=db,
                user=user,
            )
        )

        assert latest.batch_id == 8
        assert detail.batch_id == 7
        assert detail.status == "partial"
        assert detail.succeeded == 1
        assert detail.failed == 1
        assert detail.progress_percent == 100
        assert {group.key for group in detail.provider_groups} == {"deepseek", "qianwen"}
        assert detail.question_groups[0].label == "Token 统一管控平台哪家好？"
        assert [task.job_id for task in detail.tasks] == [71, 72]
        assert detail.tasks[1].error_message == "模型响应超时"


def test_decision_map_accepts_the_same_canonical_batch_id_without_queue_jobs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed_ledger(db)
        result = get_decision_map(
            1,
            period_days=30,
            model_key=None,
            scope="high",
            batch_id=7,
            db=db,
            user=SimpleNamespace(id=1, company_id=1, role="company_admin"),
        )

        assert result["metric_scope"]["batch_id"] == 7
        assert result["metric_scope"]["measurement_basis"] == "single_batch"
        assert result["sample_count"] == 0
