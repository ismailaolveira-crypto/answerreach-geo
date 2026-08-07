import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.models import (
    AnswerAnalysis,
    CitationSource,
    Company,
    Competitor,
    CrawlResult,
    CrawlSchedule,
    CrawlTask,
    CrawlTaskLog,
    Keyword,
    LLMProvider,
    MentionedEntity,
    Project,
    QueueJob,
    TargetQuestion,
    UsageRecord,
    User,
)
from app.services.auth import hash_password


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_schedule_queue_loop_testclient.json"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _cleanup_project_crawl_artifacts(db, project_id: int) -> None:
    task_ids = list(db.scalars(select(CrawlTask.id).where(CrawlTask.project_id == project_id)))
    result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project_id)))
    db.execute(delete(QueueJob).where(QueueJob.payload_json["project_id"].as_integer() == project_id))
    if result_ids:
        db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(result_ids)))
        db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
        db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
        db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
        db.execute(delete(CrawlResult).where(CrawlResult.id.in_(result_ids)))
    if task_ids:
        db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(task_ids)))
        db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.task_id.in_(task_ids)))
        db.execute(delete(QueueJob).where(QueueJob.payload_json["task_id"].as_integer().in_(task_ids)))
        db.execute(delete(CrawlTask).where(CrawlTask.id.in_(task_ids)))
    db.execute(delete(CrawlSchedule).where(CrawlSchedule.project_id == project_id))
    db.commit()


def verify_schedule_queue_loop(
    *, output_path: Path, email: str = "geo-demo-e2e@example.com", password: str = "geo-demo-123"
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    company: Company | None = None
    project: Project | None = None
    provider: LLMProvider | None = None
    schedule: CrawlSchedule | None = None
    created_task_ids: list[int] = []
    created_result_ids: list[int] = []
    created_job_ids: list[int] = []
    tenant_company_a: Company | None = None
    tenant_company_b: Company | None = None
    tenant_project_a: Project | None = None
    tenant_project_b: Project | None = None
    tenant_user: User | None = None
    tenant_provider: LLMProvider | None = None
    tenant_task_ids: list[int] = []
    tenant_job_ids: list[int] = []

    with SessionLocal() as db:
        try:
            company = Company(
                name="Temp Schedule Queue Verification",
                industry="GEO 验收",
                description="Temporary company for schedule queue verification.",
                status="active",
            )
            db.add(company)
            db.flush()
            project = Project(
                company_id=company.id,
                name="Temp Schedule Queue Project",
                description="Temporary project for schedule queue verification.",
                target_industry="GEO SaaS",
                target_audience="B2B marketing team",
                status="active",
            )
            db.add(project)
            db.flush()
            _cleanup_project_crawl_artifacts(db, project.id)
            provider = LLMProvider(
                name="Temp Mock Schedule Provider",
                provider_type="mock",
                model_name="mock-geo-search",
                auth_config={},
                status="active",
            )
            db.add(provider)
            db.flush()
            question = TargetQuestion(
                project_id=project.id,
                question_text="企业做 GEO 优化服务应该怎么选？",
                question_type="core",
                priority=5,
                status="active",
            )
            keyword = Keyword(
                project_id=project.id,
                keyword="GEO 优化服务",
                keyword_type="core",
                priority=5,
                status="active",
            )
            competitor = Competitor(project_id=project.id, name="竞品验证样本", status="active")
            db.add_all([question, keyword, competitor])
            db.flush()
            schedule = CrawlSchedule(
                project_id=project.id,
                name="Temp hourly schedule verification",
                schedule_type="hourly",
                interval_hours=1,
                provider_ids=[provider.id],
                target_question_ids=[question.id],
                keyword_ids=[keyword.id],
                status="active",
                next_run_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            db.add(schedule)
            db.commit()

            client = TestClient(app)
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            ready_response = client.post(
                f"/api/queue/jobs/run-ready?project_id={project.id}&max_jobs=5",
                headers=headers,
            )
            ready_response.raise_for_status()
            ready_run = ready_response.json()
            created_task_ids = [int(task_id) for task_id in ready_run["created_task_ids"]]
            _require(len(created_task_ids) == 1, "Expected exactly one due schedule task", ready_run)
            task = db.get(CrawlTask, created_task_ids[0])
            _require(task is not None, "Created task is missing", created_task_ids)
            db.refresh(schedule)
            _require(schedule.last_run_at is not None, "Schedule last_run_at was not updated")
            next_run_at = _aware(schedule.next_run_at)
            checked_at = datetime.fromisoformat(ready_run["checked_at"])
            _require(next_run_at is not None and next_run_at > checked_at, "Schedule next_run_at was not advanced")

            queue_job = db.scalar(
                select(QueueJob)
                .where(QueueJob.payload_json["task_id"].as_integer() == task.id)
                .order_by(QueueJob.id.desc())
                .limit(1)
            )
            _require(queue_job is not None, "No queue job was created for the scheduled task")
            created_job_ids = [queue_job.id]
            db.refresh(queue_job)
            _require(queue_job.id in ready_run["ran_job_ids"], "Ready runner did not execute the created job", ready_run)
            _require(queue_job.status == "success", "Scheduled queue job did not finish successfully", queue_job.error_message)
            db.refresh(task)
            _require(task.status == "success", "Scheduled crawl task did not finish successfully", task.error_message)
            results = list(db.scalars(select(CrawlResult).where(CrawlResult.task_id == task.id)))
            created_result_ids = [result.id for result in results]
            keyword_results = [result for result in results if result.keyword_id == keyword.id]
            _require(len(results) == 4, "Expected one question result and three keyword variant results", created_result_ids)
            _require(
                len(keyword_results) == 3,
                "Expected keyword expansion to create three prompt variants",
                [result.prompt_text for result in results],
            )

            result = {
                "ok": True,
                "verification_method": "direct SQLAlchemy schedule plus queue worker, mock provider only",
                "endpoint": "/api/queue/jobs/run-ready",
                "project_id": project.id,
                "schedule": {
                    "id": schedule.id,
                    "status": schedule.status,
                    "schedule_type": schedule.schedule_type,
                    "interval_hours": schedule.interval_hours,
                    "last_run_at_set": schedule.last_run_at is not None,
                    "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
                },
                "due_run": {
                    "checked_at": checked_at.isoformat(),
                    "created_task_ids": created_task_ids,
                    "created_queue_job_ids": created_job_ids,
                    "ran_job_ids": ready_run["ran_job_ids"],
                    "remaining_pending_due_jobs": ready_run["pending_job_count"],
                },
                "worker": {
                    "job_id": queue_job.id,
                    "job_status": queue_job.status,
                    "task_id": task.id,
                    "task_status": task.status,
                    "result_count": len(results),
                    "keyword_variant_count": len(keyword_results),
                },
                "safety": {
                    "real_provider_calls": 0,
                    "api_keys_used": False,
                    "temporary_data_cleaned": True,
                },
            }

            tenant_company_a = Company(
                name="Temp Queue Tenant A",
                industry="GEO 验收",
                description="Temporary company for queue tenant verification.",
                status="active",
            )
            tenant_company_b = Company(
                name="Temp Queue Tenant B",
                industry="GEO 验收",
                description="Temporary company for queue tenant verification.",
                status="active",
            )
            db.add_all([tenant_company_a, tenant_company_b])
            db.flush()
            tenant_user = User(
                company_id=tenant_company_a.id,
                name="Temp Queue Company Admin",
                email=f"temp-queue-admin-{tenant_company_a.id}@example.com",
                password_hash=hash_password("temp-queue-pass"),
                role="company_admin",
                status="active",
            )
            tenant_project_a = Project(
                company_id=tenant_company_a.id,
                name="Temp Queue Tenant A Project",
                description="Queue tenant isolation A.",
                target_industry="GEO SaaS",
                target_audience="B2B marketing team",
                status="active",
            )
            tenant_project_b = Project(
                company_id=tenant_company_b.id,
                name="Temp Queue Tenant B Project",
                description="Queue tenant isolation B.",
                target_industry="GEO SaaS",
                target_audience="B2B marketing team",
                status="active",
            )
            tenant_provider = LLMProvider(
                name="Temp Queue Tenant Mock Provider",
                provider_type="mock",
                model_name="mock-geo-search",
                auth_config={},
                status="active",
            )
            db.add_all([tenant_user, tenant_project_a, tenant_project_b, tenant_provider])
            db.flush()
            tenant_question_a = TargetQuestion(
                project_id=tenant_project_a.id,
                question_text="企业 A 如何验证 GEO 队列隔离？",
                question_type="core",
                priority=5,
                status="active",
            )
            tenant_question_b = TargetQuestion(
                project_id=tenant_project_b.id,
                question_text="企业 B 如何验证 GEO 队列隔离？",
                question_type="core",
                priority=5,
                status="active",
            )
            db.add_all([tenant_question_a, tenant_question_b])
            db.flush()
            tenant_task_a = CrawlTask(
                project_id=tenant_project_a.id,
                task_type="manual_batch",
                schedule_type="manual",
                provider_ids=[tenant_provider.id],
                target_question_ids=[tenant_question_a.id],
                keyword_ids=[],
                status="pending",
            )
            tenant_task_b = CrawlTask(
                project_id=tenant_project_b.id,
                task_type="manual_batch",
                schedule_type="manual",
                provider_ids=[tenant_provider.id],
                target_question_ids=[tenant_question_b.id],
                keyword_ids=[],
                status="pending",
            )
            db.add_all([tenant_task_a, tenant_task_b])
            db.flush()
            tenant_job_a = QueueJob(
                job_type="crawl_task.run",
                status="pending",
                priority=10,
                scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
                payload_json={
                    "task_id": tenant_task_a.id,
                    "project_id": tenant_project_a.id,
                    "provider_ids": [tenant_provider.id],
                    "target_question_ids": [tenant_question_a.id],
                    "keyword_ids": [],
                },
            )
            tenant_job_b = QueueJob(
                job_type="crawl_task.run",
                status="pending",
                priority=10,
                scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
                payload_json={
                    "task_id": tenant_task_b.id,
                    "project_id": tenant_project_b.id,
                    "provider_ids": [tenant_provider.id],
                    "target_question_ids": [tenant_question_b.id],
                    "keyword_ids": [],
                },
            )
            db.add_all([tenant_job_a, tenant_job_b])
            db.commit()
            tenant_task_ids = [tenant_task_a.id, tenant_task_b.id]
            tenant_job_ids = [tenant_job_a.id, tenant_job_b.id]

            tenant_login = client.post(
                "/api/auth/login",
                json={"email": tenant_user.email, "password": "temp-queue-pass"},
            )
            tenant_login.raise_for_status()
            tenant_headers = {"Authorization": f"Bearer {tenant_login.json()['access_token']}"}
            tenant_list_response = client.get("/api/queue/jobs", headers=tenant_headers)
            tenant_list_response.raise_for_status()
            tenant_list = tenant_list_response.json()
            tenant_visible_job_ids = {item["id"] for item in tenant_list["jobs"]}
            _require(tenant_job_a.id in tenant_visible_job_ids, "Tenant A job missing from tenant queue list", tenant_list)
            _require(tenant_job_b.id not in tenant_visible_job_ids, "Tenant B job leaked into tenant queue list", tenant_list)
            _require(
                tenant_list["summary"]["total"] == 1,
                "Tenant queue summary should only count accessible jobs",
                tenant_list["summary"],
            )

            tenant_run_response = client.post("/api/queue/jobs/run-next", headers=tenant_headers)
            tenant_run_response.raise_for_status()
            tenant_run = tenant_run_response.json()
            db.refresh(tenant_job_a)
            db.refresh(tenant_job_b)
            db.refresh(tenant_task_a)
            db.refresh(tenant_task_b)
            _require(tenant_run["ran"] is True, "Tenant queue run-next did not run an accessible job", tenant_run)
            _require(tenant_run["job"]["id"] == tenant_job_a.id, "Tenant queue ran another company job", tenant_run)
            _require(tenant_job_a.status == "success", "Tenant A job did not complete", tenant_job_a.status)
            _require(tenant_task_a.status == "success", "Tenant A task did not complete", tenant_task_a.status)
            _require(tenant_job_b.status == "pending", "Tenant B job should remain pending", tenant_job_b.status)
            _require(tenant_task_b.status == "pending", "Tenant B task should remain pending", tenant_task_b.status)
            result["tenant_isolation"] = {
                "company_admin_company_id": tenant_company_a.id,
                "visible_job_ids": sorted(tenant_visible_job_ids),
                "hidden_job_id": tenant_job_b.id,
                "ran_job_id": tenant_run["job"]["id"],
                "other_company_job_status": tenant_job_b.status,
                "summary_total": tenant_list["summary"]["total"],
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if tenant_task_ids:
                tenant_result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.task_id.in_(tenant_task_ids))))
                if tenant_result_ids:
                    db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(tenant_result_ids)))
                    db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(tenant_result_ids)))
                    db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(tenant_result_ids)))
                    db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(tenant_result_ids)))
                    db.execute(delete(CrawlResult).where(CrawlResult.id.in_(tenant_result_ids)))
                db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(tenant_task_ids)))
                db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.task_id.in_(tenant_task_ids)))
                db.execute(delete(QueueJob).where(QueueJob.payload_json["task_id"].as_integer().in_(tenant_task_ids)))
                db.execute(delete(CrawlTask).where(CrawlTask.id.in_(tenant_task_ids)))
            if tenant_job_ids:
                db.execute(delete(QueueJob).where(QueueJob.id.in_(tenant_job_ids)))
            if tenant_project_a is not None:
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == tenant_project_a.id))
                db.execute(delete(Project).where(Project.id == tenant_project_a.id))
            if tenant_project_b is not None:
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == tenant_project_b.id))
                db.execute(delete(Project).where(Project.id == tenant_project_b.id))
            if tenant_user is not None:
                db.execute(delete(User).where(User.id == tenant_user.id))
            if tenant_provider is not None:
                db.execute(delete(LLMProvider).where(LLMProvider.id == tenant_provider.id))
            if tenant_company_a is not None:
                db.execute(delete(Company).where(Company.id == tenant_company_a.id))
            if tenant_company_b is not None:
                db.execute(delete(Company).where(Company.id == tenant_company_b.id))
            if created_result_ids:
                db.execute(delete(UsageRecord).where(UsageRecord.crawl_result_id.in_(created_result_ids)))
                db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(created_result_ids)))
                db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(created_result_ids)))
                db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(created_result_ids)))
                db.execute(delete(CrawlResult).where(CrawlResult.id.in_(created_result_ids)))
            if created_task_ids:
                db.execute(delete(UsageRecord).where(UsageRecord.task_id.in_(created_task_ids)))
                db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.task_id.in_(created_task_ids)))
                db.execute(delete(QueueJob).where(QueueJob.payload_json["task_id"].as_integer().in_(created_task_ids)))
                db.execute(delete(CrawlTask).where(CrawlTask.id.in_(created_task_ids)))
            if schedule is not None:
                db.execute(delete(CrawlSchedule).where(CrawlSchedule.id == schedule.id))
            if project is not None:
                _cleanup_project_crawl_artifacts(db, project.id)
                db.execute(delete(Competitor).where(Competitor.project_id == project.id))
                db.execute(delete(Keyword).where(Keyword.project_id == project.id))
                db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project.id))
                db.execute(delete(Project).where(Project.id == project.id))
            if provider is not None:
                db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
            if company is not None:
                db.execute(delete(Company).where(Company.id == company.id))
            db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify due schedule -> queue -> worker loop without real provider calls.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = verify_schedule_queue_loop(output_path=args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
