from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register every mapped table before create_all
from app.db.session import Base
from app.models import QueueJob, QueueWorkerHeartbeat
from app.services.job_queue import claim_next_job, recover_orphaned_jobs
from app.services.worker_heartbeat import (
    HeartbeatFailureBudget,
    WorkerRegistration,
    as_utc,
    get_workspace_worker_status,
    online_global_workers,
    register_worker,
    stop_worker,
    touch_or_register_worker,
)


def test_heartbeat_failure_budget_requires_sustained_failure_and_resets() -> None:
    budget = HeartbeatFailureBudget(limit=3)

    assert budget.record_failure() is False
    assert budget.record_failure() is False
    budget.record_success()
    assert budget.consecutive_failures == 0
    assert budget.record_failure() is False
    assert budget.record_failure() is False
    assert budget.record_failure() is True


def test_missing_heartbeat_row_is_re_registered() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    registration = WorkerRegistration(
        worker_id="managed:test",
        mode="continuous",
        hostname="test-host",
        process_id=404,
        concurrency=8,
        workspace_id=None,
        observation_batch_id=None,
    )
    with Session(engine) as db:
        assert touch_or_register_worker(db, registration, now=now) == "registered"
        assert touch_or_register_worker(
            db, registration, now=now + timedelta(seconds=15)
        ) == "touched"
        worker = db.scalar(
            select(QueueWorkerHeartbeat).where(
                QueueWorkerHeartbeat.worker_id == registration.worker_id
            )
        )
        assert worker is not None
        assert as_utc(worker.last_seen_at) == now + timedelta(seconds=15)


def test_workspace_worker_status_uses_heartbeat_and_excludes_batch_receipts() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        register_worker(
            db,
            worker_id="queue:once:1",
            mode="once",
            hostname="test-host",
            process_id=100,
            concurrency=125,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )
        register_worker(
            db,
            worker_id="queue:test:1",
            mode="continuous",
            hostname="test-host",
            process_id=101,
            concurrency=8,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )
        register_worker(
            db,
            worker_id="queue:stopped:1",
            mode="continuous",
            hostname="test-host",
            process_id=103,
            concurrency=32,
            workspace_id=1,
            observation_batch_id=None,
            now=now + timedelta(seconds=1),
        )
        stop_worker(db, "queue:stopped:1", now=now + timedelta(seconds=2))
        register_worker(
            db,
            worker_id="queue:diagnostic:1",
            mode="continuous",
            hostname="test-host",
            process_id=102,
            concurrency=125,
            workspace_id=1,
            observation_batch_id=85,
            now=now,
        )
        db.add_all(
            [
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    scheduled_at=now,
                    payload_json={"workspace_id": 1, "dispatch_enabled": True},
                ),
                QueueJob(
                    job_type="geo_observation.collect",
                    status="running",
                    started_at=now,
                    scheduled_at=now,
                    payload_json={"workspace_id": 1, "worker_id": "queue:test:1"},
                ),
                QueueJob(
                    job_type="geo_observation.batch",
                    status="running",
                    started_at=now - timedelta(days=1),
                    scheduled_at=now,
                    payload_json={"workspace_id": 1},
                ),
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    scheduled_at=now,
                    payload_json={"workspace_id": 2, "dispatch_enabled": True},
                ),
            ]
        )
        db.commit()

        status = get_workspace_worker_status(db, 1, now=now)

        assert status["online"] is True
        assert status["worker_count"] == 1
        assert status["concurrency"] == 8
        assert status["last_seen_at"] == now
        assert status["pending_jobs"] == 1
        assert status["historical_jobs"] == 0
        assert status["running_jobs"] == 1
        assert status["stale_running_jobs"] == 0

        stop_worker(db, "queue:test:1", now=now + timedelta(seconds=1))
        stopped = get_workspace_worker_status(db, 1, now=now + timedelta(seconds=1))
        assert stopped["online"] is False
        assert stopped["last_seen_at"] is not None


def test_recover_orphaned_job_requeues_only_executable_offline_work() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(
            QueueWorkerHeartbeat(
                worker_id="queue:dead:1",
                status="stopped",
                mode="continuous",
                hostname="dead-host",
                process_id=202,
                concurrency=1,
                started_at=now - timedelta(minutes=10),
                last_seen_at=now - timedelta(minutes=5),
                stopped_at=now - timedelta(minutes=5),
            )
        )
        child = QueueJob(
            job_type="geo_observation.collect",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=now - timedelta(minutes=5),
            started_at=now - timedelta(minutes=5),
            payload_json={
                "workspace_id": 1,
                "worker_id": "queue:dead:1",
                "dispatch_enabled": True,
            },
        )
        parent = QueueJob(
            job_type="geo_observation.batch",
            status="running",
            attempts=0,
            max_attempts=1,
            scheduled_at=now - timedelta(days=1),
            started_at=now - timedelta(days=1),
            payload_json={"workspace_id": 1},
        )
        db.add_all([child, parent])
        db.commit()
        child_id = child.id
        parent_id = parent.id

        result = recover_orphaned_jobs(db, now=now, workspace_id=1)

        recovered = db.get(QueueJob, child_id)
        receipt = db.get(QueueJob, parent_id)
        assert result == {"recovered": 1, "failed": 0}
        assert recovered is not None and recovered.status == "pending"
        assert recovered.payload_json["worker_id"] is None
        assert recovered.payload_json["recovery_count"] == 1
        assert receipt is not None and receipt.status == "running"


def test_periodic_recovery_waits_for_expired_owner_then_recovers_once() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        register_worker(
            db,
            worker_id="queue:crashed:1",
            mode="continuous",
            hostname="test-host",
            process_id=505,
            concurrency=8,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )
        job = QueueJob(
            job_type="geo_observation.collect",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=now - timedelta(minutes=5),
            started_at=now - timedelta(minutes=5),
            payload_json={
                "workspace_id": 1,
                "worker_id": "queue:crashed:1",
                "dispatch_enabled": True,
            },
        )
        db.add(job)
        db.commit()
        job_id = job.id

        assert recover_orphaned_jobs(db, now=now) == {"recovered": 0, "failed": 0}
        assert db.get(QueueJob, job_id).status == "running"

        after_expiry = now + timedelta(seconds=121)
        assert recover_orphaned_jobs(db, now=after_expiry) == {
            "recovered": 1,
            "failed": 0,
        }
        assert recover_orphaned_jobs(db, now=after_expiry) == {
            "recovered": 0,
            "failed": 0,
        }
        recovered = db.get(QueueJob, job_id)
        assert recovered.status == "pending"
        assert recovered.payload_json["recovery_count"] == 1


def test_online_global_workers_can_require_exact_process_id() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        register_worker(
            db,
            worker_id="queue:global:301",
            mode="continuous",
            hostname="test-host",
            process_id=301,
            concurrency=8,
            workspace_id=None,
            observation_batch_id=None,
            now=now,
        )
        register_worker(
            db,
            worker_id="queue:scoped:302",
            mode="continuous",
            hostname="test-host",
            process_id=302,
            concurrency=8,
            workspace_id=1,
            observation_batch_id=None,
            now=now,
        )

        assert [worker.process_id for worker in online_global_workers(db, now=now)] == [301]
        assert len(online_global_workers(db, process_id=301, now=now)) == 1
        assert online_global_workers(db, process_id=302, now=now) == []


def test_global_claims_balance_concurrent_workspaces_before_draining_old_backlog() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        for index in range(4):
            db.add(
                QueueJob(
                    job_type="geo_observation.collect",
                    status="pending",
                    priority=10,
                    scheduled_at=now,
                    payload_json={
                        "workspace_id": 1,
                        "sequence": index,
                        "dispatch_enabled": True,
                    },
                )
            )
        db.add(
            QueueJob(
                job_type="geo_observation.collect",
                status="pending",
                priority=10,
                scheduled_at=now,
                payload_json={
                    "workspace_id": 2,
                    "sequence": 0,
                    "dispatch_enabled": True,
                },
            )
        )
        db.commit()

        first = claim_next_job(db, now=now, worker_id="queue:fair:1")
        second = claim_next_job(db, now=now, worker_id="queue:fair:1")

        assert first is not None and first.payload_json["workspace_id"] == 1
        assert second is not None and second.payload_json["workspace_id"] == 2


def test_worker_never_claims_historical_observations_without_page_submission_marker() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        historical = QueueJob(
            job_type="geo_observation.collect",
            status="pending",
            priority=100,
            scheduled_at=now - timedelta(days=1),
            payload_json={"workspace_id": 1, "observation_ledger_batch_id": 40},
        )
        fresh = QueueJob(
            job_type="geo_observation.collect",
            status="pending",
            priority=10,
            scheduled_at=now,
            payload_json={
                "workspace_id": 2,
                "observation_ledger_batch_id": 90,
                "dispatch_enabled": True,
                "dispatch_source": "current_page_submission",
            },
        )
        db.add_all([historical, fresh])
        db.commit()
        historical_id = historical.id
        fresh_id = fresh.id

        claimed = claim_next_job(db, now=now, worker_id="queue:selection-only:1")
        assert claimed is not None and claimed.id == fresh_id
        assert db.get(QueueJob, historical_id).status == "pending"
        assert claim_next_job(db, now=now, worker_id="queue:selection-only:1") is None

        status = get_workspace_worker_status(db, 1, now=now)
        assert status["pending_jobs"] == 0
        assert status["historical_jobs"] == 1
        assert "不会执行" in status["message"]
