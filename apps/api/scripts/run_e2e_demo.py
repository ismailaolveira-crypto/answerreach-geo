import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.api.routes.content import (
    confirm_public_delivery_report,
    create_delivery_package_share,
    get_placement_impact,
)
from app.api.routes.projects import run_project_stage_goal_action
from app.db.session import Base, SessionLocal, engine
from app.models import (
    Company,
    Competitor,
    Keyword,
    LLMProvider,
    MaturityReport,
    MaturityScoreItem,
    ArticleDraft,
    ArticleReview,
    AnswerAnalysis,
    CitationSource,
    ContentAsset,
    ContentAssetReview,
    CrawlResult,
    CrawlSchedule,
    CrawlTask,
    CrawlTaskLog,
    DeliveryPackageAccessLog,
    DeliveryPackageShare,
    MentionedEntity,
    PlacementRecord,
    Project,
    ProjectStageGoal,
    QueueJob,
    SystemAlert,
    TargetQuestion,
    UsageRecord,
    User,
)
from app.schemas.content import DeliveryPackageShareCreate, PublicDeliveryConfirmRequest
from app.schemas.report import MaturityReportCreate
from app.schemas.search import CrawlTaskCreate
from app.services.auth import hash_password
from app.services.crawl_runner import create_crawl_task
from app.services.job_queue import run_job
from app.services.maturity_report import generate_maturity_report


DEMO_PASSWORD = "geo-demo-123"
DEMO_EMAIL = "geo-demo-e2e@example.com"
DEMO_COMPANY_NAME = "GEO 演示企业"
DEMO_PROJECT_PREFIX = "GEO 闭环演示项目"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[3] / "outputs" / "latest_e2e_demo.json"

QUESTIONS = [
    "企业做 GEO 优化应该从哪些目标问题开始？",
    "AI 搜索会根据什么信源推荐企业服务商？",
    "网络安全培训公司哪家更适合大型企业？",
    "企业如何提高在大模型答案中的被推荐概率？",
    "AI 更容易采信官网内容还是媒体报道？",
    "GEO 成熟度应该如何客观评估？",
    "企业内容投放后如何复盘 AI 搜索效果？",
    "面向 AI 的 FAQ 内容应该怎么写？",
    "大模型推荐服务商时会看哪些案例证据？",
    "企业如何发现竞品在 AI 答案里的优势信源？",
]

KEYWORDS = [
    "GEO 优化服务",
    "AI 搜索优化",
    "大模型答案监测",
    "企业内容投放复盘",
    "AI 信源采信",
    "生成式搜索优化",
    "网络安全培训服务商",
    "企业知识库内容优化",
    "AI 可引用内容结构",
    "GEO 成熟度评估",
]

COMPETITORS = [
    ("星图智能", ["星图 GEO", "Xingtu AI"]),
    ("云策增长", ["云策 GEO", "Yunce Growth"]),
    ("知源咨询", ["知源 AI", "ZhiYuan"]),
]

PROVIDERS = [
    ("豆包搜索模拟", "mock-doubao-search"),
    ("Kimi 搜索模拟", "mock-kimi-search"),
    ("通义搜索模拟", "mock-qwen-search"),
]


def _print_event(step: str, data: dict[str, Any]) -> None:
    print(json.dumps({"step": step, **data}, ensure_ascii=False), flush=True)


def _one(db: Session, model: type, **filters: Any):
    stmt = select(model)
    for field, value in filters.items():
        stmt = stmt.where(getattr(model, field) == value)
    return db.scalar(stmt.limit(1))


def _delete_project_tree(db: Session, project_id: int) -> None:
    task_ids = list(db.scalars(select(CrawlTask.id).where(CrawlTask.project_id == project_id)))
    result_ids = list(db.scalars(select(CrawlResult.id).where(CrawlResult.project_id == project_id)))
    report_ids = list(db.scalars(select(MaturityReport.id).where(MaturityReport.project_id == project_id)))
    draft_ids = list(db.scalars(select(ArticleDraft.id).where(ArticleDraft.project_id == project_id)))
    asset_ids = list(db.scalars(select(ContentAsset.id).where(ContentAsset.project_id == project_id)))

    if result_ids:
        db.execute(delete(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(result_ids)))
        db.execute(delete(MentionedEntity).where(MentionedEntity.crawl_result_id.in_(result_ids)))
        db.execute(delete(CitationSource).where(CitationSource.crawl_result_id.in_(result_ids)))
    if report_ids:
        db.execute(delete(MaturityScoreItem).where(MaturityScoreItem.report_id.in_(report_ids)))
    if draft_ids:
        db.execute(delete(ArticleReview).where(ArticleReview.article_draft_id.in_(draft_ids)))
    if asset_ids:
        db.execute(delete(ContentAssetReview).where(ContentAssetReview.content_asset_id.in_(asset_ids)))
    if task_ids:
        db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.task_id.in_(task_ids)))

    db.execute(delete(DeliveryPackageAccessLog).where(DeliveryPackageAccessLog.project_id == project_id))
    db.execute(delete(DeliveryPackageShare).where(DeliveryPackageShare.project_id == project_id))
    db.execute(delete(PlacementRecord).where(PlacementRecord.project_id == project_id))
    db.execute(delete(ArticleDraft).where(ArticleDraft.project_id == project_id))
    db.execute(delete(ContentAsset).where(ContentAsset.project_id == project_id))
    db.execute(delete(MaturityReport).where(MaturityReport.project_id == project_id))
    db.execute(delete(UsageRecord).where(UsageRecord.project_id == project_id))
    db.execute(delete(CrawlResult).where(CrawlResult.project_id == project_id))
    db.execute(delete(CrawlTaskLog).where(CrawlTaskLog.project_id == project_id))
    db.execute(delete(CrawlTask).where(CrawlTask.project_id == project_id))
    db.execute(delete(CrawlSchedule).where(CrawlSchedule.project_id == project_id))
    db.execute(delete(SystemAlert).where(SystemAlert.project_id == project_id))
    db.execute(delete(ProjectStageGoal).where(ProjectStageGoal.project_id == project_id))
    db.execute(delete(TargetQuestion).where(TargetQuestion.project_id == project_id))
    db.execute(delete(Keyword).where(Keyword.project_id == project_id))
    db.execute(delete(Competitor).where(Competitor.project_id == project_id))
    db.execute(delete(models.AuditLog).where(models.AuditLog.project_id == project_id))

    queue_jobs = list(db.scalars(select(QueueJob)))
    for job in queue_jobs:
        if int((job.payload_json or {}).get("project_id") or 0) == project_id:
            db.delete(job)

    project = db.get(Project, project_id)
    if project is not None:
        db.delete(project)


def reset_demo_projects(db: Session) -> int:
    projects = list(
        db.scalars(select(Project).where(Project.name.like(f"{DEMO_PROJECT_PREFIX}%")))
    )
    for project in projects:
        _delete_project_tree(db, project.id)
    db.commit()
    return len(projects)


def ensure_user(db: Session) -> User:
    user = _one(db, User, email=DEMO_EMAIL)
    if user is not None:
        if user.status != "active":
            user.status = "active"
        if user.role != "super_admin":
            user.role = "super_admin"
        db.flush()
        return user
    user = User(
        name="GEO 演示管理员",
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD),
        role="super_admin",
        status="active",
    )
    db.add(user)
    db.flush()
    return user


def ensure_company(db: Session) -> Company:
    company = _one(db, Company, name=DEMO_COMPANY_NAME)
    if company is not None:
        return company
    company = Company(
        name=DEMO_COMPANY_NAME,
        industry="企业 AI 搜索优化与网络安全培训",
        website_url="https://geo-demo.example.com",
        description="用于演示 GEO 优化平台完整闭环的样例企业。",
        brand_aliases=["GEO Demo", "GEO演示"],
        status="active",
    )
    db.add(company)
    db.flush()
    return company


def create_project(db: Session, company: Company, run_label: str) -> Project:
    project = Project(
        company_id=company.id,
        name=f"{DEMO_PROJECT_PREFIX} {run_label}",
        description="覆盖搜索采集、成熟度报告、撰稿、审核、投放、复盘、客户交付确认的一键演示项目。",
        target_industry="企业 AI 搜索优化 / 网络安全培训",
        target_audience="企业市场负责人、品牌负责人、内容运营与销售负责人",
        status="active",
    )
    db.add(project)
    db.flush()
    return project


def seed_geo_config(db: Session, project: Project) -> tuple[list[TargetQuestion], list[Keyword]]:
    questions = [
        TargetQuestion(project_id=project.id, question_text=text, question_type="core", priority=5)
        for text in QUESTIONS
    ]
    keywords = [
        Keyword(project_id=project.id, keyword=text, keyword_type="industry", priority=5)
        for text in KEYWORDS
    ]
    competitors = [
        Competitor(
            project_id=project.id,
            name=name,
            aliases=aliases,
            website_url=f"https://{name.lower().replace(' ', '-')}.example.com",
            description="演示竞品，用于形成 AI 答案中的竞争提及。",
        )
        for name, aliases in COMPETITORS
    ]
    db.add_all([*questions, *keywords, *competitors])
    db.flush()
    return questions, keywords


def ensure_providers(db: Session) -> list[LLMProvider]:
    providers: list[LLMProvider] = []
    for name, model_name in PROVIDERS:
        provider = _one(db, LLMProvider, name=name)
        if provider is None:
            provider = LLMProvider(
                name=name,
                provider_type="mock",
                model_name=model_name,
                status="active",
                auth_config={},
                cost_rule={"input_per_1k": 0, "output_per_1k": 0, "currency": "CNY"},
            )
            db.add(provider)
            db.flush()
        elif provider.status != "active":
            provider.status = "active"
            db.flush()
        providers.append(provider)
    return providers


def generate_two_reports(db: Session, project: Project) -> tuple[MaturityReport, MaturityReport]:
    baseline = generate_maturity_report(
        db,
        project,
        MaturityReportCreate(title="GEO 成熟度基线报告", report_period="演示基线"),
    )
    baseline.total_score = max(0, baseline.total_score - 8)
    baseline.maturity_level = "L2 偶发可见" if baseline.total_score < 41 else baseline.maturity_level
    baseline.summary = f"{baseline.summary or ''}（演示基线：仍需补齐高质量信源与内容结构。）"
    db.flush()
    target = generate_maturity_report(
        db,
        project,
        MaturityReportCreate(title="GEO 成熟度优化报告", report_period="演示优化后"),
    )
    return baseline, target


def weaken_pre_publish_baseline(db: Session, project_id: int, baseline_at: datetime | None) -> int:
    if baseline_at is None:
        return 0
    analyses = list(
        db.scalars(
            select(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(CrawlResult.collected_at < baseline_at)
            .order_by(AnswerAnalysis.id.asc())
        )
    )
    changed = 0
    for index, analysis in enumerate(analyses):
        if index % 2 == 0:
            analysis.company_mentioned = False
            analysis.company_recommended = False
            analysis.company_rank = None
            analysis.sentiment = "neutral"
            analysis.confidence = 45
            analysis.analysis_json = {
                **(analysis.analysis_json or {}),
                "demo_adjustment": "weak_pre_publish_baseline",
            }
            changed += 1
    db.flush()
    return changed


def run_stage_goal_flow(db: Session, project: Project, user: User) -> dict[str, Any]:
    goal = ProjectStageGoal(
        project_id=project.id,
        title="完成 GEO MVP 闭环演示",
        metric_key="accepted_delivery_count",
        baseline_value=0,
        target_value=1,
        due_at=datetime.now(UTC) + timedelta(days=7),
        owner="GEO 演示管理员",
        note="由一键端到端演示脚本创建，覆盖采集、撰稿、审核、投放、复盘和交付确认。",
    )
    db.add(goal)
    db.flush()
    db.commit()
    db.refresh(goal)

    action_results = []
    for action_type in [
        "run_crawl",
        "generate_draft",
        "approve_and_create_placement",
        "publish_prepare_delivery",
        "create_delivery_followup",
    ]:
        result = run_project_stage_goal_action(project.id, goal.id, action_type, db=db, user=user)
        action_results.append(result.model_dump())

    placement_result = next(
        item for item in action_results if item["action_type"] == "publish_prepare_delivery"
    )
    placement_id = int(placement_result["resource_id"])
    placement = db.get(PlacementRecord, placement_id)
    if placement is not None:
        placement.target_url = "https://geo-demo.example.com/solutions/geo-mvp-demo"
        placement.notes = f"{placement.notes or ''}\n演示投放页已设置为可被 AI 采信的结构化解决方案页。".strip()
        weakened_baseline_count = weaken_pre_publish_baseline(db, project.id, placement.published_at)
        db.commit()
    else:
        weakened_baseline_count = 0

    processed_jobs: list[dict[str, Any]] = []
    detail = placement_result.get("detail") or {}
    review_job_id = detail.get("review_queue_job_id")
    if not review_job_id and detail.get("review_alert_id"):
        alert = db.get(SystemAlert, int(detail["review_alert_id"]))
        review_job_id = (alert.detail_json or {}).get("review_queue_job_id") if alert else None
    if review_job_id:
        job = db.get(QueueJob, int(review_job_id))
        if job is not None:
            job = run_job(db, job)
            processed_jobs.append(
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "status": job.status,
                    "error_message": job.error_message,
                }
            )

    share = create_delivery_package_share(
        project.id,
        DeliveryPackageShareCreate(name="GEO MVP 闭环演示交付包"),
        db=db,
        user=user,
    )
    access_log = confirm_public_delivery_report(
        share.token,
        placement_id,
        PublicDeliveryConfirmRequest(
            actor_name="演示客户",
            comment="已确认收到 GEO MVP 闭环演示交付报告。",
        ),
        db=db,
        user_agent="geo-e2e-demo-script",
    )
    db.refresh(goal)
    impact = get_placement_impact(project.id, placement_id, db)
    return {
        "goal_id": goal.id,
        "goal_status": goal.status,
        "action_results": action_results,
        "placement_id": placement_id,
        "share_id": share.id,
        "share_token": share.token,
        "access_log_id": access_log.id,
        "processed_jobs": processed_jobs,
        "weakened_baseline_count": weakened_baseline_count,
        "review_status": impact.review_report["status"],
        "metric_deltas": impact.review_report["metric_deltas"],
        "delivery_status": impact.review_report["archive"]["delivery_status"],
    }


def run_demo(*, output_path: Path | None = None, reset: bool = False) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    run_label = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    with SessionLocal() as db:
        if reset:
            deleted_count = reset_demo_projects(db)
            _print_event("reset_completed", {"deleted_project_count": deleted_count})

        user = ensure_user(db)
        company = ensure_company(db)
        providers = ensure_providers(db)
        project = create_project(db, company, run_label)
        questions, keywords = seed_geo_config(db, project)
        db.commit()

        _print_event(
            "seeded",
            {
                "company_id": company.id,
                "project_id": project.id,
                "question_count": len(questions),
                "keyword_count": len(keywords),
                "provider_count": len(providers),
            },
        )

        crawl_task = create_crawl_task(
            db,
            project,
            CrawlTaskCreate(
                task_type="e2e_demo_batch",
                schedule_type="manual",
                provider_ids=[provider.id for provider in providers],
                target_question_ids=[question.id for question in questions],
                keyword_ids=[keyword.id for keyword in keywords],
                execute_now=True,
            ),
        )
        _print_event("crawl_completed", {"task_id": crawl_task.id, "status": crawl_task.status})

        baseline_report, target_report = generate_two_reports(db, project)
        db.commit()
        _print_event(
            "reports_generated",
            {
                "baseline_report_id": baseline_report.id,
                "baseline_score": baseline_report.total_score,
                "target_report_id": target_report.id,
                "target_score": target_report.total_score,
                "target_level": target_report.maturity_level,
            },
        )

        stage_goal_result = run_stage_goal_flow(db, project, user)
        _print_event("stage_goal_flow_completed", stage_goal_result)

        result = {
            "run_label": run_label,
            "generated_at": datetime.now(UTC).isoformat(),
            "login": {"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
            "company_id": company.id,
            "project_id": project.id,
            "project_url": f"/projects/{project.id}",
            "crawl_task_id": crawl_task.id,
            "report_ids": [baseline_report.id, target_report.id],
            "latest_report_url": f"/projects/{project.id}/reports/{target_report.id}",
            "compare_url": f"/projects/{project.id}/reports/compare",
            "delivery_package_url": f"/projects/{project.id}/delivery-package",
            "public_share_url": f"/share/delivery/{stage_goal_result['share_token']}",
            "stage_goal": stage_goal_result,
        }
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result["output_path"] = str(output_path)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"step": "demo_ready", **result}, ensure_ascii=False, indent=2), flush=True)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and run a complete GEO MVP demo flow.")
    parser.add_argument("--reset", action="store_true", help="Delete prior script-created demo projects first.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for the stable JSON run summary.",
    )
    args = parser.parse_args()
    run_demo(output_path=args.output, reset=args.reset)


if __name__ == "__main__":
    main()
