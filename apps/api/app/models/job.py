from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    column,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin

_PAYLOAD_JSON = column("payload_json", JSON)


class QueueJob(TimestampMixin, Base):
    __tablename__ = "queue_jobs"
    __table_args__ = (
        Index(
            "uq_queue_job_active_fingerprint",
            "job_type",
            _PAYLOAD_JSON["workspace_id"].as_string(),
            _PAYLOAD_JSON["input_fingerprint"].as_string(),
            unique=True,
            sqlite_where=text(
                "status IN ('pending', 'running', 'recovering') "
                "AND json_extract(payload_json, '$.input_fingerprint') IS NOT NULL "
                "AND json_extract(payload_json, '$.input_fingerprint') != ''"
            ),
            postgresql_where=text(
                "status IN ('pending', 'running', 'recovering') "
                "AND COALESCE(payload_json->>'input_fingerprint', '') <> ''"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class QueueWorkerHeartbeat(TimestampMixin, Base):
    """Durable liveness record for a queue worker process.

    Local Agent nodes have a different trust boundary and must never be used as
    proof that the paid observation queue is being consumed.
    """

    __tablename__ = "queue_worker_heartbeats"
    __table_args__ = (UniqueConstraint("worker_id", name="uq_queue_worker_heartbeat_worker_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    worker_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="continuous")
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_workspaces_v1.id"), index=True
    )
    observation_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("geo_observation_batches_v1.id"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
