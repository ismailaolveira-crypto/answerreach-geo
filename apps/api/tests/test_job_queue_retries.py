from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register every mapped table before create_all
from app.db.session import Base
from app.models import QueueJob
from app.services.job_queue import (
    claim_next_job,
    count_ready_jobs,
    is_transient_job_error,
    retry_delay_seconds,
)


def test_transient_network_errors_are_retryable() -> None:
    assert is_transient_job_error(TimeoutError("The read operation timed out"))
    assert is_transient_job_error(ConnectionResetError("Connection reset by peer"))
    assert is_transient_job_error(RuntimeError("HTTP 503 upstream unavailable"))


def test_configuration_errors_are_not_retryable() -> None:
    assert not is_transient_job_error(ValueError("API key is invalid"))
    assert not is_transient_job_error(ValueError("model does not exist"))


def test_retry_backoff_is_bounded() -> None:
    assert [retry_delay_seconds(value) for value in (1, 2, 3, 8)] == [3, 6, 12, 30]


def test_claim_next_job_can_be_scoped_to_workspace() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add_all(
            [
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    priority=10,
                    scheduled_at=now,
                    payload_json={
                        "workspace_id": 2,
                        "observation_ledger_batch_id": 85,
                        "dispatch_enabled": True,
                    },
                ),
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    priority=1,
                    scheduled_at=now,
                    payload_json={
                        "workspace_id": 1,
                        "observation_ledger_batch_id": 85,
                        "dispatch_enabled": True,
                    },
                ),
            ]
        )
        db.commit()

        claimed = claim_next_job(
            db,
            now=now,
            workspace_id=1,
            observation_batch_id=85,
            worker_id="queue:test:1",
        )

        assert claimed is not None
        assert claimed.payload_json["workspace_id"] == 1
        assert claimed.payload_json["observation_ledger_batch_id"] == 85
        assert claimed.payload_json["worker_id"] == "queue:test:1"


def test_count_ready_jobs_excludes_frozen_history_and_honors_scope() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add_all(
            [
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    scheduled_at=now,
                    payload_json={
                        "workspace_id": 1,
                        "observation_ledger_batch_id": 90,
                        "dispatch_enabled": True,
                    },
                ),
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    scheduled_at=now,
                    payload_json={
                        "workspace_id": 1,
                        "observation_ledger_batch_id": 89,
                        "dispatch_enabled": False,
                    },
                ),
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    scheduled_at=now,
                    payload_json={
                        "workspace_id": 2,
                        "observation_ledger_batch_id": 91,
                        "dispatch_enabled": True,
                    },
                ),
            ]
        )
        db.commit()

        assert count_ready_jobs(db, now=now) == 2
        assert count_ready_jobs(db, now=now, workspace_id=1) == 1
        assert count_ready_jobs(db, now=now, observation_batch_id=90) == 1
