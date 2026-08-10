from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register every mapped table before create_all
from app.db.session import Base
from app.models import GeoObservationBatch, GeoObservationTask, QueueJob
from app.services.job_queue import sync_observation_task_from_job


def test_queue_result_automatically_updates_task_and_batch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        batch = GeoObservationBatch(
            workspace_id=1,
            source_type="official_api",
            status="pending",
            provider_count=1,
            question_count=1,
            repeat_count=1,
            total_tasks=1,
            configuration={},
        )
        db.add(batch)
        db.flush()
        job = QueueJob(
            job_type="geo_observation.collect",
            status="success",
            payload_json={"workspace_id": 1, "run_id": 8, "evidence_id": 13},
            attempts=1,
            max_attempts=3,
            scheduled_at=now,
            started_at=now,
            finished_at=now,
        )
        db.add(job)
        db.flush()
        task = GeoObservationTask(
            batch_id=batch.id,
            workspace_id=1,
            queue_job_id=job.id,
            provider_key="deepseek_web_search",
            provider_label="DeepSeek",
            model_key="deepseek",
            model_label="DeepSeek",
            question_plan_id=1,
            question_text_snapshot="企业级大模型治理平台怎么选？",
            sample_key="provider:1:question:1:repeat:1",
            repeat_index=1,
            repeat_count=1,
            status="running",
        )
        db.add(task)
        db.flush()
        job.payload_json = {
            **job.payload_json,
            "observation_task_id": task.id,
        }

        sync_observation_task_from_job(db, job)
        db.flush()

        assert task.status == "completed"
        assert task.run_id == 8
        assert task.evidence_id == 13
        assert task.attempt_count == 1
        assert batch.status == "completed"
        assert batch.completed_tasks == 1
        assert batch.failed_tasks == 0


def test_queue_failure_is_persisted_in_the_same_ledger_cell() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        batch = GeoObservationBatch(
            workspace_id=1,
            source_type="official_api",
            status="running",
            provider_count=1,
            question_count=1,
            repeat_count=1,
            total_tasks=1,
            configuration={},
        )
        db.add(batch)
        db.flush()
        job = QueueJob(
            job_type="geo_observation.collect",
            status="failed",
            payload_json={"workspace_id": 1},
            attempts=3,
            max_attempts=3,
            error_message="provider timeout",
            scheduled_at=now,
            started_at=now,
            finished_at=now,
        )
        db.add(job)
        db.flush()
        task = GeoObservationTask(
            batch_id=batch.id,
            workspace_id=1,
            queue_job_id=job.id,
            provider_key="qwen_responses",
            provider_label="通义千问",
            model_key="qianwen",
            model_label="通义千问",
            question_plan_id=1,
            question_text_snapshot="企业级大模型治理平台怎么选？",
            sample_key="provider:2:question:1:repeat:1",
            repeat_index=1,
            repeat_count=1,
            status="running",
        )
        db.add(task)
        db.flush()
        job.payload_json = {**job.payload_json, "observation_task_id": task.id}

        sync_observation_task_from_job(db, job)
        db.flush()

        assert task.status == "failed"
        assert task.error_detail == "provider timeout"
        assert batch.status == "partial"
        assert batch.completed_tasks == 0
        assert batch.failed_tasks == 1


def test_receipt_and_batch_only_run_after_child_claim() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        receipt = QueueJob(
            job_type="geo_observation.batch",
            status="queued",
            attempts=0,
            max_attempts=1,
            scheduled_at=now,
            payload_json={"workspace_id": 1},
        )
        db.add(receipt)
        db.flush()
        batch = GeoObservationBatch(
            workspace_id=1,
            queue_job_id=receipt.id,
            source_type="official_api",
            status="pending",
            provider_count=1,
            question_count=1,
            repeat_count=1,
            total_tasks=1,
            configuration={},
        )
        db.add(batch)
        db.flush()
        child = QueueJob(
            job_type="geo_observation.collect",
            status="pending",
            attempts=0,
            max_attempts=3,
            scheduled_at=now,
            payload_json={"workspace_id": 1},
        )
        db.add(child)
        db.flush()
        task = GeoObservationTask(
            batch_id=batch.id,
            workspace_id=1,
            queue_job_id=child.id,
            provider_key="qwen_responses",
            provider_label="通义千问",
            model_key="qianwen",
            model_label="通义千问",
            question_plan_id=1,
            question_text_snapshot="企业级大模型治理平台怎么选？",
            sample_key="provider:2:question:1:repeat:1",
            repeat_index=1,
            repeat_count=1,
            status="pending",
        )
        db.add(task)
        db.flush()
        child.payload_json = {**child.payload_json, "observation_task_id": task.id}

        sync_observation_task_from_job(db, child)
        db.flush()
        assert batch.status == "pending"
        assert receipt.status == "queued"
        assert batch.started_at is None
        assert receipt.started_at is None

        child.status = "running"
        child.attempts = 1
        child.started_at = now
        sync_observation_task_from_job(db, child)
        db.flush()
        assert task.status == "running"
        assert batch.status == "running"
        assert receipt.status == "running"
        assert batch.started_at == now
        assert receipt.started_at == now

        child.status = "success"
        child.finished_at = now
        sync_observation_task_from_job(db, child)
        db.flush()
        assert task.status == "completed"
        assert batch.status == "completed"
        assert receipt.status == "success"
        assert batch.completed_at == now
        assert receipt.finished_at == now
