import secrets
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    WRITE_ROLES,
    assert_company_access,
    get_company_or_404,
    get_current_user,
    get_project_or_404,
    require_roles,
)
from app.db.session import get_db
from app.models import (
    AnswerAnalysis,
    ArticleDraft,
    ArticleReview,
    AuditLog,
    CitationSource,
    Competitor,
    ContentAsset,
    CrawlSchedule,
    CrawlTask,
    CrawlResult,
    DeliveryPackageAccessLog,
    DeliveryPackageShare,
    Keyword,
    LLMProvider,
    LLMProviderTestRun,
    MaturityReport,
    PlacementRecord,
    Project,
    ProjectStageGoal,
    SystemAlert,
    TargetQuestion,
    UsageRecord,
    User,
)
from app.schemas.common import APIMessage
from app.schemas.project import (
    ProjectStageGoalActionResult,
    ProjectCreate,
    ProjectDetail,
    ProjectInputReadinessCheck,
    ProjectMvpContentDelivery,
    ProjectMvpCrawlHealth,
    ProjectMvpScheduleStatus,
    ProjectMvpStatus,
    ProjectMvpStatusAction,
    ProjectMvpStatusCheck,
    ProjectMvpProviderStatus,
    ProjectMvpStatusStageGoal,
    ProjectOperatingTrendPoint,
    ProjectOperatingTrends,
    ProjectRead,
    ProjectStageGoalCreate,
    ProjectStageGoalRead,
    ProjectStageGoalTimelineItem,
    ProjectStageGoalUpdate,
    ProjectUpdate,
)
from app.schemas.alert import SystemAlertRead
from app.schemas.content import ArticleDraftGenerate
from app.schemas.search import CrawlTaskCreate
from app.services.article_workflow import decide_article_draft_review, generate_article_draft, review_article_draft
from app.services.auth import utcnow
from app.services.audit import record_audit_log
from app.services.alert import create_placement_reminder_alerts
from app.services.crawl_runner import create_crawl_task
from app.services.llm_provider import diagnose_provider
from app.services.project_goals import goal_suggested_actions

router = APIRouter(prefix="/projects", tags=["projects"])

METRIC_LABELS = {
    "health_score": "健康度",
    "maturity_score": "成熟度",
    "recommendation_rate": "推荐率",
    "approved_content_count": "已通过内容",
    "published_placement_count": "已发布投放",
    "accepted_delivery_count": "客户确认交付",
    "answer_count": "AI 答案样本",
    "browser_observation_count": "网页端观测样本",
}


def _as_aware_end(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=UTC)


def _safe_rate(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0


def _latest_provider_test(db: Session, provider_id: int) -> LLMProviderTestRun | None:
    return db.scalar(
        select(LLMProviderTestRun)
        .where(LLMProviderTestRun.provider_id == provider_id)
        .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
        .limit(1)
    )


def _provider_platform_key(provider: LLMProvider) -> str | None:
    value = f"{provider.name} {provider.provider_type} {provider.model_name}".lower()
    if "doubao" in value or "豆包" in value:
        return "doubao"
    if "deepseek" in value:
        return "deepseek"
    if "kimi" in value:
        return "kimi"
    if "qwen" in value or "千问" in value or "dashscope" in value:
        return "qwen"
    return None


def _project_operational_readiness(db: Session, project: Project) -> dict:
    question_count = db.scalar(
        select(func.count()).select_from(TargetQuestion).where(TargetQuestion.project_id == project.id)
    ) or 0
    keyword_count = db.scalar(select(func.count()).select_from(Keyword).where(Keyword.project_id == project.id)) or 0
    asset_count = db.scalar(select(func.count()).select_from(ContentAsset).where(ContentAsset.project_id == project.id)) or 0
    result_count = db.scalar(select(func.count()).select_from(CrawlResult).where(CrawlResult.project_id == project.id)) or 0
    report_count = db.scalar(select(func.count()).select_from(MaturityReport).where(MaturityReport.project_id == project.id)) or 0
    draft_count = db.scalar(select(func.count()).select_from(ArticleDraft).where(ArticleDraft.project_id == project.id)) or 0
    review_count = db.scalar(
        select(func.count())
        .select_from(ArticleReview)
        .join(ArticleDraft, ArticleDraft.id == ArticleReview.article_draft_id)
        .where(ArticleDraft.project_id == project.id)
    ) or 0
    approved_draft_count = db.scalar(
        select(func.count())
        .select_from(ArticleDraft)
        .where(ArticleDraft.project_id == project.id, ArticleDraft.status == "approved")
    ) or 0
    placement_count = db.scalar(
        select(func.count()).select_from(PlacementRecord).where(PlacementRecord.project_id == project.id)
    ) or 0
    placed_approved_draft_count = db.scalar(
        select(func.count(func.distinct(ArticleDraft.id)))
        .select_from(ArticleDraft)
        .join(PlacementRecord, PlacementRecord.article_draft_id == ArticleDraft.id)
        .where(ArticleDraft.project_id == project.id, ArticleDraft.status == "approved")
    ) or 0
    active_hourly_schedule_count = db.scalar(
        select(func.count())
        .select_from(CrawlSchedule)
        .where(
            CrawlSchedule.project_id == project.id,
            CrawlSchedule.status == "active",
            CrawlSchedule.schedule_type == "hourly",
            CrawlSchedule.interval_hours <= 1,
        )
    ) or 0
    latest_report = db.scalar(
        select(MaturityReport)
        .where(MaturityReport.project_id == project.id)
        .order_by(MaturityReport.created_at.desc(), MaturityReport.id.desc())
        .limit(1)
    )
    browser_observation_since = datetime.now(UTC) - timedelta(days=7)
    browser_result_ids = list(
        db.scalars(
            select(CrawlResult.id)
            .join(CrawlTask, CrawlTask.id == CrawlResult.task_id)
            .where(
                CrawlResult.project_id == project.id,
                CrawlTask.task_type == "browser_observation_manual",
                CrawlResult.collected_at >= browser_observation_since,
            )
        )
    )
    browser_observation_count = len(browser_result_ids)
    browser_screenshot_evidence_count = 0
    browser_observation_platforms: set[str] = set()
    if browser_result_ids:
        browser_screenshot_evidence_count = (
            db.scalar(
                select(func.count())
                .select_from(CitationSource)
                .where(
                    CitationSource.crawl_result_id.in_(browser_result_ids),
                    CitationSource.source_type == "screenshot",
                )
            )
            or 0
        )
        for analysis in db.scalars(select(AnswerAnalysis).where(AnswerAnalysis.crawl_result_id.in_(browser_result_ids))):
            observation = (analysis.analysis_json or {}).get("browser_observation") or {}
            platform_name = str(observation.get("platform_name") or "").strip()
            if platform_name:
                browser_observation_platforms.add(platform_name)
    providers = list(
        db.scalars(
            select(LLMProvider)
            .where(LLMProvider.provider_type.not_in(["mock", "browser_observation"]))
            .order_by(LLMProvider.id)
        )
    )
    platform_labels = {
        "doubao": "豆包/火山方舟",
        "deepseek": "DeepSeek",
        "kimi": "Kimi",
        "qwen": "千问",
    }
    platform_status: dict[str, dict] = {
        key: {
            "key": key,
            "label": label,
            "configured": False,
            "active": False,
            "latest_test_ok": False,
            "project_result_count": 0,
            "ready": False,
            "provider_ids": [],
            "blockers": [],
        }
        for key, label in platform_labels.items()
    }
    for provider in providers:
        platform_key = _provider_platform_key(provider)
        if platform_key is None:
            continue
        item = platform_status[platform_key]
        diagnostic = diagnose_provider(provider)
        latest_test = _latest_provider_test(db, provider.id)
        provider_result_count = db.scalar(
            select(func.count()).select_from(CrawlResult).where(
                CrawlResult.project_id == project.id,
                CrawlResult.provider_id == provider.id,
            )
        ) or 0
        item["configured"] = True
        item["active"] = item["active"] or provider.status == "active"
        item["latest_test_ok"] = item["latest_test_ok"] or bool(latest_test and latest_test.ok)
        item["project_result_count"] += int(provider_result_count)
        item["provider_ids"].append(provider.id)
        missing = [str(value) for value in diagnostic.get("missing", [])]
        config_missing = [value for value in missing if value != "status=active"]
        if config_missing:
            item["blockers"].append(f"{provider.name} 缺配置：{'、'.join(config_missing)}")
        if latest_test is not None and not latest_test.ok:
            item["blockers"].append(f"{provider.name} 最近测试失败：{latest_test.error_message or '未知错误'}")
        if diagnostic.get("last_blocker"):
            item["blockers"].append(f"{provider.name} 历史 blocker：{diagnostic['last_blocker']}")
        if provider.status != "active":
            item["blockers"].append(f"{provider.name} 未启用")
        if latest_test is None:
            item["blockers"].append(f"{provider.name} 尚未完成测试调用")
    for item in platform_status.values():
        item["ready"] = bool(item["active"] and item["latest_test_ok"] and item["project_result_count"] > 0)
        item["blockers"] = list(dict.fromkeys(item["blockers"]))[:4]

    ready_platform_count = sum(1 for item in platform_status.values() if item["ready"])
    checks = [
        {
            "key": "project_inputs",
            "label": "目标问题和关键词",
            "ok": question_count >= 10 and keyword_count >= 10,
            "detail": f"目标问题 {question_count}/10，关键词 {keyword_count}/10",
            "next_action": "补齐目标问题和关键词" if question_count < 10 or keyword_count < 10 else None,
        },
        {
            "key": "content_assets",
            "label": "企业资料入库",
            "ok": asset_count > 0,
            "detail": f"企业资料 {asset_count} 份",
            "next_action": "上传/录入产品白皮书、FAQ、演示稿" if asset_count == 0 else None,
        },
        {
            "key": "multi_model_results",
            "label": "多模型真实采集",
            "ok": ready_platform_count >= 3 and result_count >= 10,
            "detail": f"已就绪平台 {ready_platform_count}/4，真实结果 {result_count} 条",
            "next_action": "继续配置 Kimi/千问并补跑真实采集" if ready_platform_count < 3 else None,
        },
        {
            "key": "browser_observation_evidence",
            "label": "网页观测留证",
            "ok": len(browser_observation_platforms) >= 4 and browser_screenshot_evidence_count >= 4,
            "detail": (
                f"近7天网页观测 {browser_observation_count} 条，截图证据 {browser_screenshot_evidence_count} 条，"
                f"平台 {len(browser_observation_platforms)} 个"
            ),
            "next_action": (
                "录入豆包、DeepSeek、Kimi、千问四个平台的网页端答案和截图证据"
                if len(browser_observation_platforms) < 4 or browser_screenshot_evidence_count < 4
                else None
            ),
        },
        {
            "key": "hourly_monitoring",
            "label": "每小时监测",
            "ok": active_hourly_schedule_count > 0,
            "detail": f"活跃每小时计划 {active_hourly_schedule_count} 个",
            "next_action": "创建或恢复每小时采集计划" if active_hourly_schedule_count == 0 else None,
        },
        {
            "key": "maturity_report",
            "label": "成熟度报告",
            "ok": report_count > 0,
            "detail": f"报告 {report_count} 份，最新分数 {latest_report.total_score if latest_report else '暂无'}",
            "next_action": "采集后生成成熟度报告" if report_count == 0 else None,
        },
        {
            "key": "draft_review_loop",
            "label": "撰稿和 AI 评分",
            "ok": draft_count > 0 and review_count > 0,
            "detail": f"稿件 {draft_count} 篇，评分 {review_count} 条",
            "next_action": "基于报告生成稿件并评分" if draft_count == 0 or review_count == 0 else None,
        },
        {
            "key": "human_delivery_loop",
            "label": "人工审核和投放承接",
            "ok": placed_approved_draft_count > 0,
            "detail": f"人工通过稿件 {approved_draft_count} 篇，已绑定投放 {placed_approved_draft_count} 篇，投放记录 {placement_count} 条",
            "next_action": "人工通过高分稿件并绑定投放计划" if placed_approved_draft_count == 0 else None,
        },
    ]
    ok_count = sum(1 for item in checks if item["ok"])
    if ok_count == len(checks):
        status = "ready"
        summary = "正式可持续运行"
    elif ready_platform_count >= 1 and report_count > 0 and draft_count > 0 and review_count > 0:
        status = "partial"
        summary = "核心闭环可用，但多平台和人工投放闭环仍需补齐"
    else:
        status = "blocked"
        summary = "真实采集或内容闭环尚未跑通"
    return {
        "project_id": project.id,
        "status": status,
        "summary": summary,
        "ok_count": ok_count,
        "check_count": len(checks),
        "ready_platform_count": ready_platform_count,
        "required_platform_count": len(platform_status),
        "platforms": list(platform_status.values()),
        "checks": checks,
        "metrics": {
            "question_count": int(question_count),
            "keyword_count": int(keyword_count),
            "content_asset_count": int(asset_count),
            "crawl_result_count": int(result_count),
            "maturity_report_count": int(report_count),
            "article_draft_count": int(draft_count),
            "article_review_count": int(review_count),
            "approved_draft_count": int(approved_draft_count),
            "placed_approved_draft_count": int(placed_approved_draft_count),
            "placement_count": int(placement_count),
            "active_hourly_schedule_count": int(active_hourly_schedule_count),
            "recent_browser_observation_count": int(browser_observation_count),
            "recent_browser_screenshot_evidence_count": int(browser_screenshot_evidence_count),
            "recent_browser_observation_platform_count": len(browser_observation_platforms),
        },
        "updated_at": utcnow().isoformat(),
    }


def _project_metric_values(db: Session, project_id: int, until: datetime | None = None) -> dict[str, float]:
    result_stmt = select(CrawlResult.id).where(CrawlResult.project_id == project_id)
    report_stmt = select(MaturityReport).where(MaturityReport.project_id == project_id)
    draft_stmt = select(ArticleDraft).where(ArticleDraft.project_id == project_id)
    asset_stmt = select(ContentAsset).where(ContentAsset.project_id == project_id)
    placement_stmt = select(PlacementRecord).where(PlacementRecord.project_id == project_id)
    alert_stmt = select(SystemAlert).where(SystemAlert.project_id == project_id)
    if until is not None:
        result_stmt = result_stmt.where(func.coalesce(CrawlResult.collected_at, CrawlResult.created_at) <= until)
        report_stmt = report_stmt.where(func.coalesce(MaturityReport.generated_at, MaturityReport.created_at) <= until)
        draft_stmt = draft_stmt.where(ArticleDraft.created_at <= until)
        asset_stmt = asset_stmt.where(ContentAsset.created_at <= until)
        placement_stmt = placement_stmt.where(PlacementRecord.created_at <= until)
        alert_stmt = alert_stmt.where(SystemAlert.created_at <= until)

    result_ids = list(db.scalars(result_stmt))
    answer_count = len(result_ids)
    browser_observation_stmt = (
        select(func.count())
        .select_from(CrawlResult)
        .join(CrawlTask, CrawlTask.id == CrawlResult.task_id)
        .where(CrawlResult.project_id == project_id)
        .where(CrawlTask.task_type == "browser_observation_manual")
    )
    if until is not None:
        browser_observation_stmt = browser_observation_stmt.where(
            func.coalesce(CrawlResult.collected_at, CrawlResult.created_at) <= until
        )
    browser_observation_count = db.scalar(browser_observation_stmt) or 0
    recommendation_count = 0
    mention_count = 0
    if result_ids:
        recommendation_count = (
            db.scalar(
                select(func.count())
                .select_from(AnswerAnalysis)
                .where(
                    AnswerAnalysis.crawl_result_id.in_(result_ids),
                    AnswerAnalysis.company_recommended.is_(True),
                )
            )
            or 0
        )
        mention_count = (
            db.scalar(
                select(func.count())
                .select_from(AnswerAnalysis)
                .where(
                    AnswerAnalysis.crawl_result_id.in_(result_ids),
                    AnswerAnalysis.company_mentioned.is_(True),
                )
            )
            or 0
        )

    latest_report = db.scalars(
        report_stmt.order_by(
            func.coalesce(MaturityReport.generated_at, MaturityReport.created_at).desc(),
            MaturityReport.id.desc(),
        )
    ).first()
    maturity_score = latest_report.total_score if latest_report is not None else 0
    approved_draft_count = (
        db.scalar(select(func.count()).select_from(draft_stmt.where(ArticleDraft.status == "approved").subquery()))
        or 0
    )
    approved_asset_count = (
        db.scalar(select(func.count()).select_from(asset_stmt.where(ContentAsset.status == "approved").subquery()))
        or 0
    )
    published_placement_count = (
        db.scalar(
            select(func.count()).select_from(placement_stmt.where(PlacementRecord.status == "published").subquery())
        )
        or 0
    )
    deliverable_count = (
        db.scalar(
            select(func.count()).select_from(
                placement_stmt.where(
                    PlacementRecord.visibility == "customer_visible",
                    PlacementRecord.delivery_status.in_(["ready", "delivered", "accepted"]),
                ).subquery()
            )
        )
        or 0
    )
    accepted_delivery_count = (
        db.scalar(
            select(func.count()).select_from(
                placement_stmt.where(PlacementRecord.delivery_status == "accepted").subquery()
            )
        )
        or 0
    )
    follow_up_count = (
        db.scalar(
            select(func.count()).select_from(
                alert_stmt.where(
                    SystemAlert.alert_type == "delivery.confirmed",
                    SystemAlert.status.in_(["open", "acknowledged"]),
                ).subquery()
            )
        )
        or 0
    )
    approved_content_count = approved_draft_count + approved_asset_count
    recommendation_rate = _safe_rate(recommendation_count, answer_count)
    mention_rate = _safe_rate(mention_count, answer_count)
    health_score = round(
        min(45, maturity_score * 0.45)
        + min(20, recommendation_rate * 20)
        + min(15, published_placement_count * 3)
        + min(10, accepted_delivery_count * 5)
        + min(10, approved_content_count * 2)
    )
    return {
        "maturity_score": float(maturity_score),
        "health_score": float(health_score),
        "answer_count": float(answer_count),
        "browser_observation_count": float(browser_observation_count),
        "mention_rate": mention_rate,
        "recommendation_rate": recommendation_rate,
        "approved_content_count": float(approved_content_count),
        "published_placement_count": float(published_placement_count),
        "deliverable_count": float(deliverable_count),
        "accepted_delivery_count": float(accepted_delivery_count),
        "follow_up_count": float(follow_up_count),
    }


def _goal_with_progress(db: Session, goal: ProjectStageGoal) -> ProjectStageGoalRead:
    values = _project_metric_values(db, goal.project_id)
    current = values.get(goal.metric_key, 0)
    span = goal.target_value - goal.baseline_value
    progress = 1.0 if span <= 0 and current >= goal.target_value else _safe_rate(
        max(0, current - goal.baseline_value), span if span > 0 else 1
    )
    due_at = _aware(goal.due_at)
    due_days_remaining = None
    if due_at is not None:
        due_days_remaining = (due_at.date() - utcnow().date()).days
    risk_level = _goal_risk_level(goal, progress, due_days_remaining)
    active_alert = _active_goal_alert(db, goal.id)
    review_summary, recommendations = _goal_review(goal, current, progress, risk_level)
    suggested_actions = goal_suggested_actions(goal, risk_level)
    return ProjectStageGoalRead(
        **ProjectStageGoalRead.model_validate(goal).model_dump(
            exclude={
                "current_value",
                "progress_rate",
                "remaining_value",
                "risk_level",
                "review_summary",
                "recommendations",
                "suggested_actions",
                "due_days_remaining",
                "active_alert_type",
            }
        ),
        current_value=round(current, 4),
        progress_rate=round(min(1, progress), 4),
        remaining_value=round(max(0, goal.target_value - current), 4),
        risk_level=risk_level,
        review_summary=review_summary,
        recommendations=recommendations,
        suggested_actions=suggested_actions,
        due_days_remaining=due_days_remaining,
        active_alert_type=active_alert.alert_type if active_alert is not None else None,
    )


def _get_stage_goal_or_404(db: Session, project_id: int, goal_id: int) -> ProjectStageGoal:
    goal = db.get(ProjectStageGoal, goal_id)
    if goal is None or goal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Stage goal not found")
    return goal


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _goal_risk_level(goal: ProjectStageGoal, progress: float, due_days_remaining: int | None) -> str:
    if goal.status == "completed" or progress >= 1:
        return "completed"
    if goal.status == "archived":
        return "archived"
    if due_days_remaining is None:
        return "on_track" if progress >= 0.4 else "watch"
    if due_days_remaining < 0:
        return "overdue"
    if due_days_remaining <= 3 and progress < 0.8:
        return "at_risk"
    if progress < 0.35:
        return "watch"
    return "on_track"


def _goal_review(goal: ProjectStageGoal, current: float, progress: float, risk_level: str) -> tuple[str, list[str]]:
    metric_name = METRIC_LABELS.get(goal.metric_key, goal.metric_key)
    percent = round(min(1, progress) * 100)
    summary = f"{metric_name} 当前为 {round(current, 4)}，目标为 {goal.target_value}，完成度 {percent}%。"
    if risk_level == "completed":
        summary += " 该目标已经达到或被标记完成，可以进入复盘沉淀。"
    elif risk_level == "overdue":
        summary += " 该目标已超过截止时间，建议立即拆解差距并安排补救动作。"
    elif risk_level == "at_risk":
        summary += " 该目标临近截止且进度偏低，需要优先处理。"
    elif risk_level == "watch":
        summary += " 当前进度偏低，建议提前干预。"
    else:
        summary += " 当前节奏基本可控。"

    recommendation_map = {
        "health_score": [
            "优先生成最新成熟度报告，确认健康度低分来自采集、内容、投放还是交付。",
            "把未复盘投放加入复盘队列，补齐经营视图里的证据链。",
            "围绕高频目标问题补充已审核内容，并进入 planned 投放计划。",
        ],
        "maturity_score": [
            "重新跑跨模型采集并生成成熟度报告，避免用旧样本判断成熟度。",
            "补齐信源缺口，对未被 AI 采信的高价值信源规划内容投放。",
            "把报告建议拆成内容、投放、复盘三个阶段任务。",
        ],
        "recommendation_rate": [
            "优先查看 AI 答案详情，确认未推荐时竞品和信源的共同出现模式。",
            "围绕能触发推荐的目标问题撰写高结构化内容，增强实体、场景和证据表达。",
            "检查被引用信源是否已有投放，优先投放 AI 可爬、权威、稳定的页面。",
        ],
        "approved_content_count": [
            "从成熟度报告的 next_content_topics 里挑选主题生成稿件。",
            "把待审核稿件推进到人工审核，减少内容生产在审核环节堆积。",
            "对低分历史稿件先做 GEO 评分，按建议重写后再进入投放。",
        ],
        "published_placement_count": [
            "从信源与投放页把已通过内容加入 planned 投放计划。",
            "优先发布 AI 已采信但我方未投放的信源内容。",
            "为 planned 投放补充 planned_at，避免进入逾期提醒。",
        ],
        "accepted_delivery_count": [
            "将客户可见的正向复盘报告加入交付包，并生成分享链接。",
            "跟进客户确认记录，把确认后的问题回写到项目待跟进事项。",
            "对未确认报告补充复盘摘要和下一步建议，降低客户阅读成本。",
        ],
        "answer_count": [
            "检查模型渠道状态和采集计划，确保目标问题和关键词都进入定时任务。",
            "按 10 个目标问题和 10 个关键词跑跨 Provider 采集，扩大样本覆盖。",
            "失败任务优先重试，避免成熟度报告样本可信度不足。",
        ],
        "browser_observation_count": [
            "优先按报告的问题缺口和关键词缺口完成网页端抽样观测。",
            "每条网页观测都应录入原始答案、截图或录屏地址，以及页面可见信源。",
            "对比 API 样本和网页端样本差异，标记需要人工复核的问题。",
        ],
    }
    return summary, recommendation_map.get(goal.metric_key, ["复盘该指标的当前值、目标值和责任人，拆解下一步动作。"])


def _active_goal_alert(db: Session, goal_id: int) -> SystemAlert | None:
    alerts = db.scalars(
        select(SystemAlert)
        .where(
            SystemAlert.status.in_(["open", "acknowledged"]),
            SystemAlert.alert_type.in_(["stage_goal.overdue", "stage_goal.at_risk"]),
        )
        .order_by(SystemAlert.created_at.desc())
    )
    return next((alert for alert in alerts if int(alert.detail_json.get("stage_goal_id") or 0) == goal_id), None)


def _has_active_goal_alert(existing_alerts: list[SystemAlert], *, alert_type: str, goal_id: int) -> bool:
    return any(
        alert.alert_type == alert_type
        and int(alert.detail_json.get("stage_goal_id") or 0) == goal_id
        and alert.status in {"open", "acknowledged"}
        for alert in existing_alerts
    )


def _goal_action_topic(goal: ProjectStageGoal) -> str:
    metric_name = METRIC_LABELS.get(goal.metric_key, goal.metric_key)
    return f"{goal.title}：围绕{metric_name}提升的 GEO 优化内容"


def _goal_draft_source_context(goal: ProjectStageGoal, action_type: str) -> dict:
    return {
        "stage_goal_id": goal.id,
        "stage_goal_title": goal.title,
        "stage_goal_metric_key": goal.metric_key,
        "stage_goal_metric_name": METRIC_LABELS.get(goal.metric_key, goal.metric_key),
        "stage_goal_action_type": action_type,
    }


def _latest_approved_content(db: Session, project_id: int) -> tuple[ArticleDraft | None, ContentAsset | None]:
    draft = db.scalar(
        select(ArticleDraft)
        .where(ArticleDraft.project_id == project_id, ArticleDraft.status == "approved")
        .order_by(ArticleDraft.updated_at.desc(), ArticleDraft.id.desc())
        .limit(1)
    )
    asset = db.scalar(
        select(ContentAsset)
        .where(ContentAsset.project_id == project_id, ContentAsset.status == "approved")
        .order_by(ContentAsset.updated_at.desc(), ContentAsset.id.desc())
        .limit(1)
    )
    return draft, asset


def _stage_goal_resource_url(project_id: int, resource_type: str | None, resource_id: int | None) -> str | None:
    if resource_type == "crawl_task" and resource_id:
        return f"/projects/{project_id}/tasks/{resource_id}"
    if resource_type == "article_draft" and resource_id:
        return f"/projects/{project_id}/drafts/{resource_id}"
    if resource_type == "article_review" and resource_id:
        return "/reviews"
    if resource_type == "placement_record" and resource_id:
        return f"/projects/{project_id}/sources"
    if resource_type == "system_alert" and resource_id:
        return "/admin/alerts"
    if resource_type == "delivery_package_access_log" and resource_id:
        return f"/projects/{project_id}/delivery-package"
    return None


def _latest_stage_goal_draft_id(db: Session, project_id: int, goal_id: int) -> int | None:
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .where(AuditLog.action == "stage_goal.action.generate_draft_and_review")
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    for log in logs:
        if int(log.detail_json.get("stage_goal_id") or 0) == goal_id:
            draft_id = log.detail_json.get("draft_id")
            return int(draft_id) if draft_id else None
    return None


def _latest_stage_goal_placement_id(db: Session, project_id: int, goal_id: int) -> int | None:
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .where(
            AuditLog.action.in_(
                [
                    "stage_goal.action.create_placement",
                    "stage_goal.action.approve_and_create_placement",
                    "stage_goal.action.publish_prepare_delivery",
                ]
            )
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    for log in logs:
        if int(log.detail_json.get("stage_goal_id") or 0) != goal_id:
            continue
        placement_id = log.detail_json.get("placement_id") or log.resource_id
        return int(placement_id) if placement_id else None
    return None


def _latest_visible_project(db: Session, user: User) -> Project | None:
    stmt = select(Project).where(Project.status != "deleted")
    if user.role != "super_admin":
        if user.company_id is None:
            return None
        stmt = stmt.where(Project.company_id == user.company_id)
    return db.scalar(stmt.order_by(Project.updated_at.desc(), Project.id.desc()).limit(1))


def _latest_maturity_reports(db: Session, project_id: int, limit: int = 2) -> list[MaturityReport]:
    return list(
        db.scalars(
            select(MaturityReport)
            .where(MaturityReport.project_id == project_id)
            .order_by(MaturityReport.generated_at.desc(), MaturityReport.id.desc())
            .limit(limit)
        )
    )


def _latest_stage_goal(db: Session, project_id: int) -> ProjectStageGoal | None:
    return db.scalar(
        select(ProjectStageGoal)
        .where(ProjectStageGoal.project_id == project_id)
        .order_by(
            ProjectStageGoal.status.desc(),
            ProjectStageGoal.updated_at.desc(),
            ProjectStageGoal.id.desc(),
        )
        .limit(1)
    )


def _latest_project_crawl_task_id(db: Session, project_id: int) -> int | None:
    task = db.scalar(
        select(CrawlTask)
        .where(CrawlTask.project_id == project_id)
        .order_by(CrawlTask.created_at.desc(), CrawlTask.id.desc())
        .limit(1)
    )
    return task.id if task is not None else None


def _project_crawl_health(db: Session, project_id: int) -> ProjectMvpCrawlHealth:
    tasks = list(
        db.scalars(
            select(CrawlTask)
            .where(CrawlTask.project_id == project_id)
            .order_by(CrawlTask.created_at.desc(), CrawlTask.id.desc())
            .limit(50)
        )
    )
    total_result_count = (
        db.scalar(select(func.count()).select_from(CrawlResult).where(CrawlResult.project_id == project_id)) or 0
    )
    if not tasks:
        return ProjectMvpCrawlHealth(
            status="missing",
            ok=False,
            reason="还没有搜索采集任务，成熟度报告缺少真实 AI 回答样本支撑。",
            next_action_label="发起搜索采集",
            next_action_type="run_crawl",
            next_action_url=f"/projects/{project_id}",
        )

    counts = {
        "pending": sum(1 for task in tasks if task.status == "pending"),
        "running": sum(1 for task in tasks if task.status == "running"),
        "success": sum(1 for task in tasks if task.status == "success"),
        "failed": sum(1 for task in tasks if task.status == "failed"),
    }
    latest = tasks[0]
    latest_result_count = (
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .where(CrawlResult.project_id == project_id, CrawlResult.task_id == latest.id)
        )
        or 0
    )
    if latest.status in {"pending", "running"}:
        return ProjectMvpCrawlHealth(
            status=latest.status,
            ok=False,
            total_tasks=len(tasks),
            pending_tasks=counts["pending"],
            running_tasks=counts["running"],
            success_tasks=counts["success"],
            failed_tasks=counts["failed"],
            latest_task_id=latest.id,
            latest_task_status=latest.status,
            latest_task_type=latest.task_type,
            latest_error_message=latest.error_message,
            latest_result_count=int(latest_result_count),
            total_result_count=int(total_result_count),
            reason="最近一次搜索采集仍在队列中或执行中，等待完成后再生成/刷新成熟度报告。",
            next_action_label="查看采集任务",
            next_action_type="open_task",
            next_action_url=f"/projects/{project_id}/tasks/{latest.id}",
        )
    if latest.status == "failed":
        if int(total_result_count) > 0 and counts["success"] > 0:
            return ProjectMvpCrawlHealth(
                status="degraded",
                ok=True,
                total_tasks=len(tasks),
                pending_tasks=counts["pending"],
                running_tasks=counts["running"],
                success_tasks=counts["success"],
                failed_tasks=counts["failed"],
                latest_task_id=latest.id,
                latest_task_status=latest.status,
                latest_task_type=latest.task_type,
                latest_error_message=latest.error_message,
                latest_result_count=int(latest_result_count),
                total_result_count=int(total_result_count),
                reason=(
                    "最近一次搜索采集失败，但项目已有可用 AI 回答样本；"
                    "成熟度报告可继续使用，建议处理最新失败任务后刷新数据。"
                ),
                next_action_label="处理失败任务",
                next_action_type="retry_crawl_task",
                next_action_url=f"/projects/{project_id}/tasks/{latest.id}",
            )
        return ProjectMvpCrawlHealth(
            status="failed",
            ok=False,
            total_tasks=len(tasks),
            pending_tasks=counts["pending"],
            running_tasks=counts["running"],
            success_tasks=counts["success"],
            failed_tasks=counts["failed"],
            latest_task_id=latest.id,
            latest_task_status=latest.status,
            latest_task_type=latest.task_type,
            latest_error_message=latest.error_message,
            latest_result_count=int(latest_result_count),
            total_result_count=int(total_result_count),
            reason=latest.error_message or "最近一次搜索采集失败，需要重试或检查模型渠道配置。",
            next_action_label="重试采集任务",
            next_action_type="retry_crawl_task",
            next_action_url=f"/projects/{project_id}/tasks/{latest.id}",
        )
    if total_result_count <= 0:
        return ProjectMvpCrawlHealth(
            status="empty",
            ok=False,
            total_tasks=len(tasks),
            pending_tasks=counts["pending"],
            running_tasks=counts["running"],
            success_tasks=counts["success"],
            failed_tasks=counts["failed"],
            latest_task_id=latest.id,
            latest_task_status=latest.status,
            latest_task_type=latest.task_type,
            latest_error_message=latest.error_message,
            latest_result_count=int(latest_result_count),
            total_result_count=0,
            reason="采集任务已执行，但还没有产生 AI 回答样本，请检查目标问题、关键词或模型渠道。",
            next_action_label="重新采集",
            next_action_type="run_crawl",
            next_action_url=f"/projects/{project_id}",
        )
    return ProjectMvpCrawlHealth(
        status="success",
        ok=True,
        total_tasks=len(tasks),
        pending_tasks=counts["pending"],
        running_tasks=counts["running"],
        success_tasks=counts["success"],
        failed_tasks=counts["failed"],
        latest_task_id=latest.id,
        latest_task_status=latest.status,
        latest_task_type=latest.task_type,
        latest_error_message=latest.error_message,
        latest_result_count=int(latest_result_count),
        total_result_count=int(total_result_count),
        reason="搜索采集已有可用 AI 回答样本，可以支撑成熟度报告和投放复盘。",
        next_action_label="查看采集任务",
        next_action_type="open_task",
        next_action_url=f"/projects/{project_id}/tasks/{latest.id}",
    )


def _project_schedule_status(db: Session, project_id: int) -> ProjectMvpScheduleStatus:
    schedules = list(
        db.scalars(
            select(CrawlSchedule)
            .where(CrawlSchedule.project_id == project_id)
            .order_by(CrawlSchedule.created_at.desc(), CrawlSchedule.id.desc())
        )
    )
    active_schedules = [schedule for schedule in schedules if schedule.status == "active"]
    hourly_schedules = [
        schedule
        for schedule in active_schedules
        if schedule.schedule_type == "hourly" and int(schedule.interval_hours or 0) <= 1
    ]
    now = utcnow()
    due_schedules = [
        schedule
        for schedule in active_schedules
        if schedule.next_run_at is not None and _aware(schedule.next_run_at) <= now
    ]
    latest = active_schedules[0] if active_schedules else (schedules[0] if schedules else None)
    is_ready = bool(hourly_schedules)
    if latest is None:
        return ProjectMvpScheduleStatus(
            ok=False,
            status="missing",
            next_action_label="创建每小时监测",
            next_action_type="create_crawl_schedule",
            next_action_url=f"/projects/{project_id}#crawl-schedules",
        )
    if not active_schedules:
        return ProjectMvpScheduleStatus(
            ok=False,
            status="inactive",
            active_schedule_count=0,
            hourly_schedule_count=0,
            due_schedule_count=0,
            latest_schedule_id=latest.id,
            latest_schedule_name=latest.name,
            latest_schedule_type=latest.schedule_type,
            latest_interval_hours=latest.interval_hours,
            latest_provider_count=len(latest.provider_ids or []),
            latest_target_question_count=len(latest.target_question_ids or []),
            latest_keyword_count=len(latest.keyword_ids or []),
            latest_last_run_at=latest.last_run_at,
            latest_next_run_at=latest.next_run_at,
            next_action_label="启用监测计划",
            next_action_type="enable_crawl_schedule",
            next_action_url=f"/projects/{project_id}#crawl-schedules",
        )
    return ProjectMvpScheduleStatus(
        ok=is_ready,
        status="ready" if is_ready else "needs_hourly",
        active_schedule_count=len(active_schedules),
        hourly_schedule_count=len(hourly_schedules),
        due_schedule_count=len(due_schedules),
        latest_schedule_id=latest.id,
        latest_schedule_name=latest.name,
        latest_schedule_type=latest.schedule_type,
        latest_interval_hours=latest.interval_hours,
        latest_provider_count=len(latest.provider_ids or []),
        latest_target_question_count=len(latest.target_question_ids or []),
        latest_keyword_count=len(latest.keyword_ids or []),
        latest_last_run_at=latest.last_run_at,
        latest_next_run_at=latest.next_run_at,
        next_action_label="执行到期监测" if due_schedules else "查看监测计划",
        next_action_type="run_due_crawl_schedules" if due_schedules else "open_crawl_schedules",
        next_action_url=f"/projects/{project_id}#crawl-schedules",
    )


def _latest_stage_goal_actions(db: Session, project_id: int, goal_id: int | None) -> list[ProjectMvpStatusAction]:
    if goal_id is None:
        return []
    labels = {
        "stage_goal.action.run_crawl": ("run_crawl", "已基于阶段目标发起搜索采集任务。"),
        "stage_goal.action.generate_draft_and_review": (
            "generate_draft",
            "已基于阶段目标生成 GEO 友好稿件，并完成 AI 审核评分。",
        ),
        "stage_goal.action.create_placement": ("create_placement", "已基于阶段目标创建投放计划。"),
        "stage_goal.action.approve_and_create_placement": (
            "approve_and_create_placement",
            "已将阶段目标稿件人工通过，并创建投放计划。",
        ),
        "stage_goal.action.publish_prepare_delivery": (
            "publish_prepare_delivery",
            "已发布阶段目标投放，并进入客户交付包与复盘提醒流程。",
        ),
        "stage_goal.action.create_delivery_followup": (
            "create_delivery_followup",
            "已创建阶段目标交付跟进事项。",
        ),
        "stage_goal.action.run_full_loop": (
            "run_full_loop",
            "已一键跑通阶段目标 GEO 闭环。",
        ),
    }
    logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.project_id == project_id, AuditLog.action.in_(list(labels.keys())))
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
    )
    actions: list[ProjectMvpStatusAction] = []
    seen: set[str] = set()
    for log in logs:
        if int(log.detail_json.get("stage_goal_id") or 0) != goal_id:
            continue
        action_type, message = labels[log.action]
        if action_type in seen:
            continue
        seen.add(action_type)
        resource_type = log.resource_type
        resource_id = log.resource_id
        detail = dict(log.detail_json or {})
        if action_type == "generate_draft":
            resource_type = "article_draft"
            resource_id = int(detail.get("draft_id") or resource_id or 0) or resource_id
            detail.setdefault("review_score", detail.get("total_score"))
            detail.setdefault("review_grade", detail.get("grade"))
        if action_type in {"approve_and_create_placement", "publish_prepare_delivery"}:
            resource_id = int(detail.get("placement_id") or resource_id or 0) or resource_id
            resource_type = "placement_record"
        actions.append(
            ProjectMvpStatusAction(
                action_type=action_type,
                status="created",
                message=message,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_url=_stage_goal_resource_url(project_id, resource_type, resource_id),
                detail=detail,
                created_at=log.created_at,
            )
        )
    return actions


def _latest_stage_goal_review(db: Session, project_id: int, goal_id: int | None) -> tuple[int | None, int | None]:
    if goal_id is None:
        return None, None
    draft_id = _latest_stage_goal_draft_id(db, project_id, goal_id)
    if draft_id is None:
        return None, None
    review = db.scalar(
        select(ArticleReview)
        .where(ArticleReview.article_draft_id == draft_id)
        .order_by(ArticleReview.created_at.desc(), ArticleReview.id.desc())
        .limit(1)
    )
    return draft_id, review.id if review is not None else None


def _latest_delivery_share(db: Session, project_id: int) -> DeliveryPackageShare | None:
    return db.scalar(
        select(DeliveryPackageShare)
        .where(DeliveryPackageShare.project_id == project_id, DeliveryPackageShare.status == "active")
        .order_by(DeliveryPackageShare.created_at.desc(), DeliveryPackageShare.id.desc())
        .limit(1)
    )


def _latest_delivery_access_log(db: Session, project_id: int) -> DeliveryPackageAccessLog | None:
    return db.scalar(
        select(DeliveryPackageAccessLog)
        .where(DeliveryPackageAccessLog.project_id == project_id)
        .order_by(DeliveryPackageAccessLog.created_at.desc(), DeliveryPackageAccessLog.id.desc())
        .limit(1)
    )


def _project_content_delivery_summary(db: Session, project_id: int) -> ProjectMvpContentDelivery:
    latest_review = db.scalar(
        select(ArticleReview)
        .join(ArticleDraft, ArticleDraft.id == ArticleReview.article_draft_id)
        .where(ArticleDraft.project_id == project_id)
        .order_by(ArticleReview.created_at.desc(), ArticleReview.id.desc())
        .limit(1)
    )
    latest_draft = db.get(ArticleDraft, latest_review.article_draft_id) if latest_review is not None else db.scalar(
        select(ArticleDraft)
        .where(ArticleDraft.project_id == project_id)
        .order_by(ArticleDraft.created_at.desc(), ArticleDraft.id.desc())
        .limit(1)
    )
    latest_placement = db.scalar(
        select(PlacementRecord)
        .where(PlacementRecord.project_id == project_id)
        .order_by(PlacementRecord.created_at.desc(), PlacementRecord.id.desc())
        .limit(1)
    )
    latest_share = _latest_delivery_share(db, project_id)
    latest_access_log = _latest_delivery_access_log(db, project_id)
    approved_draft_count = (
        db.scalar(
            select(func.count())
            .select_from(ArticleDraft)
            .where(ArticleDraft.project_id == project_id, ArticleDraft.status == "approved")
        )
        or 0
    )
    planned_placement_count = (
        db.scalar(
            select(func.count())
            .select_from(PlacementRecord)
            .where(PlacementRecord.project_id == project_id, PlacementRecord.status == "planned")
        )
        or 0
    )
    published_delivery_count = (
        db.scalar(
            select(func.count())
            .select_from(PlacementRecord)
            .where(
                PlacementRecord.project_id == project_id,
                PlacementRecord.status == "published",
                PlacementRecord.visibility == "customer_visible",
                PlacementRecord.delivery_status.in_(["ready", "delivered", "accepted"]),
            )
        )
        or 0
    )
    active_share_count = (
        db.scalar(
            select(func.count())
            .select_from(DeliveryPackageShare)
            .where(DeliveryPackageShare.project_id == project_id, DeliveryPackageShare.status == "active")
        )
        or 0
    )
    accepted_delivery_count = (
        db.scalar(
            select(func.count())
            .select_from(PlacementRecord)
            .where(PlacementRecord.project_id == project_id, PlacementRecord.delivery_status == "accepted")
        )
        or 0
    )
    if latest_review is None:
        next_action_label = "生成并评分稿件"
        next_action_type = "generate_draft"
        next_action_url = f"/projects/{project_id}"
    elif int(approved_draft_count) == 0:
        next_action_label = "人工通过稿件"
        next_action_type = "approve_draft"
        next_action_url = f"/projects/{project_id}/drafts/{latest_draft.id}" if latest_draft is not None else f"/projects/{project_id}"
    elif int(planned_placement_count) == 0 and int(published_delivery_count) == 0:
        next_action_label = "创建投放计划"
        next_action_type = "create_placement"
        next_action_url = f"/projects/{project_id}/placements"
    elif int(published_delivery_count) == 0:
        next_action_label = "发布并准备交付"
        next_action_type = "publish_prepare_delivery"
        next_action_url = (
            f"/projects/{project_id}/placements/{latest_placement.id}/impact"
            if latest_placement is not None
            else f"/projects/{project_id}/sources"
        )
    elif int(active_share_count) == 0:
        next_action_label = "生成客户分享链接"
        next_action_type = "create_delivery_share"
        next_action_url = f"/projects/{project_id}/delivery-package"
    elif int(accepted_delivery_count) == 0:
        next_action_label = "等待客户确认"
        next_action_type = "open_public_delivery"
        next_action_url = f"/share/delivery/{latest_share.token}" if latest_share is not None else f"/projects/{project_id}/delivery-package"
    else:
        next_action_label = "查看客户交付包"
        next_action_type = "open_delivery_package"
        next_action_url = f"/projects/{project_id}/delivery-package"
    return ProjectMvpContentDelivery(
        ok=bool(latest_review and approved_draft_count and published_delivery_count and active_share_count and accepted_delivery_count),
        latest_draft_id=latest_draft.id if latest_draft is not None else None,
        latest_review_id=latest_review.id if latest_review is not None else None,
        latest_review_score=latest_review.total_score if latest_review is not None else None,
        latest_review_grade=latest_review.grade if latest_review is not None else None,
        approved_draft_count=int(approved_draft_count),
        planned_placement_count=int(planned_placement_count),
        published_delivery_count=int(published_delivery_count),
        active_share_count=int(active_share_count),
        accepted_delivery_count=int(accepted_delivery_count),
        latest_placement_id=latest_placement.id if latest_placement is not None else None,
        latest_share_id=latest_share.id if latest_share is not None else None,
        latest_share_token=latest_share.token if latest_share is not None else None,
        latest_access_log_id=latest_access_log.id if latest_access_log is not None else None,
        next_action_label=next_action_label,
        next_action_type=next_action_type,
        next_action_url=next_action_url,
    )


def _placement_impact_summary(project_id: int, placement_id: int | None, db: Session) -> tuple[str, dict[str, float | int]]:
    if placement_id is None:
        return "missing", {}
    try:
        from app.api.routes.content import get_placement_impact

        impact = get_placement_impact(project_id, placement_id, db)
        report = impact.review_report
        status = str(report.get("status") or "unknown")
        deltas = report.get("metric_deltas") or {}
        return status, {
            "sample_size_delta": int(deltas.get("sample_size_delta") or 0),
            "company_mention_rate_delta": float(deltas.get("company_mention_rate_delta") or 0),
            "company_recommendation_rate_delta": float(deltas.get("company_recommendation_rate_delta") or 0),
            "source_after_appearances": int(deltas.get("source_after_appearances") or 0),
        }
    except Exception:
        return "unavailable", {}


def _provider_project_collection_summary(db: Session, *, project_id: int, provider_id: int) -> dict[str, int | str | None]:
    tasks = list(
        db.scalars(
            select(CrawlTask)
            .where(CrawlTask.project_id == project_id)
            .order_by(CrawlTask.created_at.desc(), CrawlTask.id.desc())
        )
    )
    provider_tasks = [task for task in tasks if provider_id in (task.provider_ids or [])]
    latest_task = provider_tasks[0] if provider_tasks else None
    latest_result = db.scalar(
        select(CrawlResult)
        .where(CrawlResult.project_id == project_id, CrawlResult.provider_id == provider_id)
        .order_by(CrawlResult.collected_at.desc().nullslast(), CrawlResult.id.desc())
        .limit(1)
    )
    result_count = (
        db.scalar(
            select(func.count()).select_from(CrawlResult).where(
                CrawlResult.project_id == project_id,
                CrawlResult.provider_id == provider_id,
            )
        )
        or 0
    )
    usage_summary = db.execute(
        select(func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
            UsageRecord.project_id == project_id,
            UsageRecord.provider_id == provider_id,
            UsageRecord.action == "crawl.answer",
        )
    ).one()
    return {
        "project_total_task_count": len(provider_tasks),
        "project_success_task_count": sum(1 for task in provider_tasks if task.status == "success"),
        "project_failed_task_count": sum(1 for task in provider_tasks if task.status == "failed"),
        "project_result_count": int(result_count),
        "project_usage_record_count": int(usage_summary[0] or 0),
        "project_total_tokens": int(usage_summary[1] or 0),
        "project_latest_task_id": latest_task.id if latest_task is not None else None,
        "project_latest_task_status": latest_task.status if latest_task is not None else None,
        "project_latest_task_error_message": latest_task.error_message if latest_task is not None else None,
        "project_latest_result_id": latest_result.id if latest_result is not None else None,
        "project_latest_result_collected_at": latest_result.collected_at if latest_result is not None else None,
    }


def _provider_readiness(
    db: Session, *, project_id: int | None = None
) -> tuple[dict[str, int | bool | str], list[ProjectMvpProviderStatus]]:
    providers = list(
        db.scalars(
            select(LLMProvider)
            .where(LLMProvider.status == "active")
            .order_by(LLMProvider.provider_type.asc(), LLMProvider.id.asc())
        )
    )
    items: list[ProjectMvpProviderStatus] = []
    for provider in providers:
        diagnostic = diagnose_provider(provider)
        latest_test = db.scalar(
            select(LLMProviderTestRun)
            .where(LLMProviderTestRun.provider_id == provider.id)
            .order_by(LLMProviderTestRun.created_at.desc(), LLMProviderTestRun.id.desc())
            .limit(1)
        )
        ready = bool(diagnostic["ready"])
        latest_test_ok = latest_test.ok if latest_test is not None else None
        if provider.provider_type == "mock":
            collection_ready = ready
            collection_blocker = None if ready else "Mock Provider 配置不完整。"
        elif not ready:
            collection_ready = False
            collection_blocker = "Provider 还缺少认证、Base URL 或模型名称。"
        elif latest_test_ok is not True:
            collection_ready = False
            collection_blocker = "真实 Provider 尚未通过最近一次测试调用。"
        else:
            collection_ready = True
            collection_blocker = None
        project_collection = (
            _provider_project_collection_summary(db, project_id=project_id, provider_id=provider.id)
            if project_id is not None
            else {}
        )
        items.append(
            ProjectMvpProviderStatus(
                provider_id=provider.id,
                name=provider.name,
                provider_type=provider.provider_type,
                model_name=provider.model_name,
                status=provider.status,
                ready=ready,
                auth_ready=bool(diagnostic["auth_ready"]),
                supports_web_search=bool(diagnostic["supports_web_search"]),
                access_method=str(diagnostic["access_method"]),
                search_mode=str(diagnostic["search_mode"]),
                search_access_status=str(diagnostic["search_access_status"]),
                collection_ready=collection_ready,
                collection_blocker=collection_blocker,
                latest_test_ok=latest_test_ok,
                latest_test_error=latest_test.error_message if latest_test is not None else None,
                **project_collection,
                missing=list(diagnostic["missing"]),
                warnings=list(diagnostic["warnings"]),
                recommendations=list(diagnostic["recommendations"]),
            )
        )
    real_ready = [item for item in items if item.provider_type != "mock" and item.ready]
    real_collection_ready = [item for item in items if item.provider_type != "mock" and item.collection_ready]
    mock_ready = [item for item in items if item.provider_type == "mock" and item.collection_ready]
    web_search_ready = [item for item in real_collection_ready if item.supports_web_search]
    summary: dict[str, int | bool | str] = {
        "total": len(items),
        "ready": sum(1 for item in items if item.ready),
        "real_ready": len(real_ready),
        "real_collection_ready": len(real_collection_ready),
        "mock_ready": len(mock_ready),
        "web_search_ready": len(web_search_ready),
        "has_real_provider": len(real_collection_ready) > 0,
        "has_web_search_provider": len(web_search_ready) > 0,
        "mode": "real" if real_collection_ready else ("mock" if mock_ready else "not_ready"),
    }
    return summary, items


def _project_input_readiness(
    *,
    target_question_count: int,
    keyword_count: int,
    competitor_count: int,
    content_asset_count: int,
    placement_count: int,
) -> tuple[int, str, list[ProjectInputReadinessCheck]]:
    checks = [
        ProjectInputReadinessCheck(
            key="target_questions",
            label="目标问题",
            current=target_question_count,
            required=10,
            ok=target_question_count >= 10,
            help_text="建议至少配置 10 个客户会问的大模型目标问题。",
        ),
        ProjectInputReadinessCheck(
            key="keywords",
            label="核心关键词",
            current=keyword_count,
            required=10,
            ok=keyword_count >= 10,
            help_text="建议至少配置 10 个品牌、产品、行业或场景关键词。",
        ),
        ProjectInputReadinessCheck(
            key="competitors",
            label="竞品",
            current=competitor_count,
            required=3,
            ok=competitor_count >= 3,
            help_text="建议配置 3-10 个竞品，用于比较 AI 推荐和答案排序。",
        ),
        ProjectInputReadinessCheck(
            key="content_assets",
            label="内容资产",
            current=content_asset_count,
            required=1,
            ok=content_asset_count >= 1,
            help_text="至少导入一篇历史稿件、官网页、案例或解决方案，便于做 GEO 审核。",
        ),
        ProjectInputReadinessCheck(
            key="placements",
            label="投放信源",
            current=placement_count,
            required=1,
            ok=placement_count >= 1,
            help_text="至少维护一个已投放或计划投放信源，用于判断 AI 是否采信。",
        ),
    ]
    score = round((sum(1 for item in checks if item.ok) / len(checks)) * 100)
    if score == 100:
        status = "ready"
    elif score >= 60:
        status = "partial"
    else:
        status = "not_ready"
    return score, status, checks


def _project_mvp_status(db: Session, project: Project, user: User) -> ProjectMvpStatus:
    latest_reports = _latest_maturity_reports(db, project.id, limit=2)
    latest_report = latest_reports[0] if latest_reports else None
    goal = _latest_stage_goal(db, project.id)
    goal_id = goal.id if goal is not None else None
    placement_id = _latest_stage_goal_placement_id(db, project.id, goal_id) if goal_id is not None else None
    placement = db.get(PlacementRecord, placement_id) if placement_id is not None else None
    share = _latest_delivery_share(db, project.id)
    access_log = _latest_delivery_access_log(db, project.id)
    review_status, metric_deltas = _placement_impact_summary(project.id, placement_id, db)
    actions = _latest_stage_goal_actions(db, project.id, goal_id)
    provider_summary, provider_items = _provider_readiness(db, project_id=project.id)
    crawl_health = _project_crawl_health(db, project.id)
    schedule_status = _project_schedule_status(db, project.id)
    content_delivery = _project_content_delivery_summary(db, project.id)
    draft_id, review_id = _latest_stage_goal_review(db, project.id, goal_id)
    if draft_id is not None and all(item.action_type != "generate_draft" for item in actions):
        actions.append(
            ProjectMvpStatusAction(
                action_type="generate_draft",
                status="created",
                message="已生成稿件并完成审核评分。",
                resource_type="article_draft",
                resource_id=draft_id,
                resource_url=f"/projects/{project.id}/drafts/{draft_id}",
                detail={"draft_id": draft_id, "review_id": review_id},
            )
        )
    deliverable_count = (
        db.scalar(
            select(func.count()).select_from(PlacementRecord).where(
                PlacementRecord.project_id == project.id,
                PlacementRecord.status == "published",
                PlacementRecord.visibility == "customer_visible",
                PlacementRecord.delivery_status.in_(["ready", "delivered", "accepted"]),
            )
        )
        or 0
    )
    timeline_count = len(actions) + (1 if access_log is not None else 0)
    has_report = latest_report is not None
    report_is_strong = latest_report is not None and latest_report.total_score >= 60
    has_completed_goal = goal is not None and goal.status == "completed"
    has_timeline = timeline_count >= 4
    has_positive_impact = (
        review_status == "positive"
        and float(metric_deltas.get("company_mention_rate_delta") or 0) > 0
        and float(metric_deltas.get("company_recommendation_rate_delta") or 0) > 0
    )
    has_delivery = share is not None and deliverable_count >= 1
    real_collection_ready_count = int(provider_summary.get("real_collection_ready") or 0)
    first_blocked_real_provider = next(
        (item for item in provider_items if item.provider_type != "mock" and not item.collection_ready),
        None,
    )
    provider_next_url = (
        f"/admin/providers/{first_blocked_real_provider.provider_id}/test?return_to=/projects/{project.id}"
        if first_blocked_real_provider is not None and first_blocked_real_provider.ready
        else "/admin/providers"
    )
    provider_next_label = (
        "测试真实渠道"
        if first_blocked_real_provider is not None and first_blocked_real_provider.ready
        else "配置真实渠道"
    )
    provider_next_type = (
        "open_provider_test"
        if first_blocked_real_provider is not None and first_blocked_real_provider.ready
        else "open_provider_config"
    )
    checks = [
        ProjectMvpStatusCheck(
            check="project.detail",
            ok=True,
            status=project.status,
            reason="项目已创建，可以继续推进采集、报告、内容和交付动作。",
            next_action_label="查看项目",
            next_action_type="open_project",
            next_action_url=f"/projects/{project.id}",
        ),
        ProjectMvpStatusCheck(
            check="crawl.health",
            ok=crawl_health.ok,
            reason=crawl_health.reason,
            next_action_label=crawl_health.next_action_label,
            next_action_type=crawl_health.next_action_type,
            next_action_url=crawl_health.next_action_url,
            status=crawl_health.status,
            event_count=crawl_health.total_result_count,
        ),
        ProjectMvpStatusCheck(
            check="crawl.schedule_ready",
            ok=schedule_status.ok,
            reason=(
                "已配置每小时搜索监测计划，可以持续采集不同大模型下的目标问答结果。"
                if schedule_status.ok
                else (
                    "已有监测计划，但不是每小时执行；建议补一个每小时计划用于 GEO 波动监控。"
                    if schedule_status.active_schedule_count > 0
                    else "还没有启用的每小时搜索监测计划，需要配置后才能稳定追踪 AI 答案变化。"
                )
            ),
            next_action_label=schedule_status.next_action_label,
            next_action_type=schedule_status.next_action_type,
            next_action_url=schedule_status.next_action_url,
            status=schedule_status.status,
            event_count=schedule_status.active_schedule_count,
        ),
        ProjectMvpStatusCheck(
            check="provider.real_collection_ready",
            ok=real_collection_ready_count > 0,
            reason=(
                "已有真实 Provider 通过测试，可用于真实大模型采集。"
                if real_collection_ready_count > 0
                else (
                    first_blocked_real_provider.collection_blocker
                    if first_blocked_real_provider is not None and first_blocked_real_provider.collection_blocker
                    else "还没有通过测试的真实 Provider；当前闭环仍以 Mock 演示为主。"
                )
            ),
            next_action_label="查看真实渠道" if real_collection_ready_count > 0 else provider_next_label,
            next_action_type="open_provider_config" if real_collection_ready_count > 0 else provider_next_type,
            next_action_url="/admin/providers" if real_collection_ready_count > 0 else provider_next_url,
            status="ready" if real_collection_ready_count > 0 else "missing",
            event_count=real_collection_ready_count,
        ),
        ProjectMvpStatusCheck(
            check="maturity_report",
            ok=has_report,
            reason=(
                "成熟度报告已生成并达到可演示分数。"
                if report_is_strong
                else (
                    "成熟度报告已生成，但分数偏低，应优先补齐搜索覆盖、可信信源和内容投放。"
                    if has_report
                    else "还没有可用成熟度报告，需要先基于搜索采集样本生成成熟度判断。"
                )
            ),
            next_action_label="查看成熟度报告" if has_report else "生成成熟度报告",
            next_action_type="open_report" if has_report else "generate_report",
            next_action_url=f"/projects/{project.id}/reports/{latest_report.id}" if latest_report is not None else None,
            total_score=latest_report.total_score if latest_report is not None else None,
            maturity_level=latest_report.maturity_level if latest_report is not None else None,
        ),
        ProjectMvpStatusCheck(
            check="stage_goal.completed",
            ok=has_completed_goal,
            reason=(
                "阶段目标已完成，说明闭环动作已经回写到运营目标。"
                if has_completed_goal
                else "阶段目标尚未完成，需要继续推进采集、内容、投放或客户确认。"
            ),
            next_action_label="查看阶段目标" if goal is not None else "创建阶段目标",
            next_action_type="open_stage_goal" if goal is not None else "create_stage_goal",
            next_action_url=f"/projects/{project.id}#stage-goals",
            status=goal.status if goal is not None else "missing",
        ),
        ProjectMvpStatusCheck(
            check="stage_goal.timeline",
            ok=has_timeline,
            reason=(
                "阶段目标时间线已有足够动作证据。"
                if has_timeline
                else "阶段目标时间线动作不足，建议先从阶段目标发起采集并生成稿件。"
            ),
            next_action_label="查看时间线" if has_timeline else "一键跑通闭环",
            next_action_type="open_stage_goal" if has_timeline else ("run_full_loop" if goal is not None else "create_stage_goal"),
            next_action_url=f"/projects/{project.id}#stage-goals",
            event_count=timeline_count,
        ),
        ProjectMvpStatusCheck(
            check="placement.impact.positive",
            ok=has_positive_impact,
            reason=(
                "投放复盘显示企业提及率和推荐率均有正向变化。"
                if has_positive_impact
                else "还没有正向投放复盘，需要发布投放并补齐投放后的采集样本。"
            ),
            next_action_label="查看投放复盘" if has_positive_impact else "一键跑通闭环",
            next_action_type=(
                "open_impact"
                if has_positive_impact
                else ("run_full_loop" if goal is not None else "open_stage_goal")
            ),
            next_action_url=(
                f"/projects/{project.id}/placements/{placement_id}/impact"
                if placement_id
                else f"/projects/{project.id}#stage-goals"
            ),
            status=review_status,
            metric_deltas=metric_deltas,
        ),
        ProjectMvpStatusCheck(
            check="public_delivery_package",
            ok=has_delivery,
            reason=(
                "客户交付包已有可交付报告和公开分享。"
                if has_delivery
                else "客户交付包还没有可交付报告或公开分享链接。"
            ),
            next_action_label="查看客户交付包" if has_delivery else "准备客户交付",
            next_action_type="open_delivery_package",
            next_action_url=f"/projects/{project.id}/delivery-package",
            deliverable_count=int(deliverable_count),
        ),
        ProjectMvpStatusCheck(
            check="content_delivery.loop",
            ok=content_delivery.ok,
            reason=(
                "内容交付闭环已有稿件评分、人工通过、客户可见投放、分享链接和客户确认。"
                if content_delivery.ok
                else "内容交付闭环还没完全跑通，需要继续推进稿件、投放、分享或客户确认。"
            ),
            next_action_label=content_delivery.next_action_label,
            next_action_type=content_delivery.next_action_type,
            next_action_url=content_delivery.next_action_url,
            status="verified" if content_delivery.ok else "pending",
            event_count=content_delivery.accepted_delivery_count,
            deliverable_count=content_delivery.published_delivery_count,
        ),
    ]
    blocking_checks = [
        item for item in checks if item.check not in {"provider.real_collection_ready", "crawl.schedule_ready"}
    ]
    return ProjectMvpStatus(
        generated_at=utcnow(),
        ok=all(item.ok for item in blocking_checks),
        user_email=user.email,
        company_id=project.company_id,
        project_id=project.id,
        project_url=f"/projects/{project.id}",
        crawl_task_id=_latest_project_crawl_task_id(db, project.id),
        report_ids=[report.id for report in reversed(latest_reports)],
        latest_report_url=f"/projects/{project.id}/reports/{latest_report.id}" if latest_report is not None else None,
        compare_url=f"/projects/{project.id}/reports/compare" if len(latest_reports) >= 2 else None,
        delivery_package_url=f"/projects/{project.id}/delivery-package",
        public_share_url=f"/share/delivery/{share.token}" if share is not None else None,
        provider_summary=provider_summary,
        providers=provider_items,
        crawl_health=crawl_health,
        schedule_status=schedule_status,
        content_delivery=content_delivery,
        stage_goal=ProjectMvpStatusStageGoal(
            goal_id=goal_id,
            goal_status=goal.status if goal is not None else "missing",
            action_results=actions,
            placement_id=placement_id,
            share_id=share.id if share is not None else None,
            share_token=share.token if share is not None else None,
            access_log_id=access_log.id if access_log is not None else None,
            review_status=review_status,
            metric_deltas=metric_deltas,
            delivery_status=placement.delivery_status if placement is not None else "missing",
        ),
        checks=checks,
    )


@router.get("", response_model=list[ProjectRead])
def list_projects(
    company_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Project]:
    stmt = select(Project).order_by(Project.created_at.desc())
    if user.role != "super_admin":
        if user.company_id is None:
            return []
        if company_id is not None and company_id != user.company_id:
            return []
        stmt = stmt.where(Project.company_id == user.company_id)
    elif company_id is not None:
        stmt = stmt.where(Project.company_id == company_id)
    return list(db.scalars(stmt))


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> Project:
    get_company_or_404(db, payload.company_id)
    assert_company_access(user, payload.company_id)
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/mvp-status/latest", response_model=ProjectMvpStatus)
def get_latest_project_mvp_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectMvpStatus:
    project = _latest_visible_project(db, user)
    if project is None:
        raise HTTPException(status_code=404, detail="No visible project found")
    return _project_mvp_status(db, project, user)


@router.get("/{project_id}/mvp-status", response_model=ProjectMvpStatus)
def get_project_mvp_status(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectMvpStatus:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    return _project_mvp_status(db, project, user)


@router.get("/{project_id}/operational-readiness")
def get_project_operational_readiness(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    return _project_operational_readiness(db, project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ProjectDetail:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    target_question_count = (
        db.scalar(select(func.count()).select_from(TargetQuestion).where(TargetQuestion.project_id == project_id))
        or 0
    )
    keyword_count = db.scalar(select(func.count()).select_from(Keyword).where(Keyword.project_id == project_id)) or 0
    competitor_count = (
        db.scalar(select(func.count()).select_from(Competitor).where(Competitor.project_id == project_id)) or 0
    )
    content_asset_count = (
        db.scalar(select(func.count()).select_from(ContentAsset).where(ContentAsset.project_id == project_id)) or 0
    )
    placement_count = (
        db.scalar(select(func.count()).select_from(PlacementRecord).where(PlacementRecord.project_id == project_id)) or 0
    )
    readiness_score, readiness_status, readiness_checks = _project_input_readiness(
        target_question_count=int(target_question_count),
        keyword_count=int(keyword_count),
        competitor_count=int(competitor_count),
        content_asset_count=int(content_asset_count),
        placement_count=int(placement_count),
    )
    return ProjectDetail(
        **ProjectRead.model_validate(project).model_dump(),
        target_question_count=int(target_question_count),
        keyword_count=int(keyword_count),
        competitor_count=int(competitor_count),
        content_asset_count=int(content_asset_count),
        placement_count=int(placement_count),
        diagnostic_readiness_score=readiness_score,
        diagnostic_readiness_status=readiness_status,
        diagnostic_readiness_checks=readiness_checks,
    )


@router.get("/{project_id}/operating-trends", response_model=ProjectOperatingTrends)
def get_project_operating_trends(
    project_id: int,
    days: int = 14,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectOperatingTrends:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    safe_days = max(7, min(days, 90))
    today = datetime.now(UTC).date()
    start_day = today - timedelta(days=safe_days - 1)
    points: list[ProjectOperatingTrendPoint] = []
    for offset in range(safe_days):
        current_day = start_day + timedelta(days=offset)
        values = _project_metric_values(db, project_id, until=_as_aware_end(current_day))
        points.append(
            ProjectOperatingTrendPoint(
                date=current_day.isoformat(),
                maturity_score=int(values["maturity_score"]),
                health_score=int(values["health_score"]),
                answer_count=int(values["answer_count"]),
                browser_observation_count=int(values["browser_observation_count"]),
                recommendation_rate=values["recommendation_rate"],
                approved_content_count=int(values["approved_content_count"]),
                published_placement_count=int(values["published_placement_count"]),
                accepted_delivery_count=int(values["accepted_delivery_count"]),
            )
        )
    return ProjectOperatingTrends(project_id=project_id, days=safe_days, points=points)


@router.get("/{project_id}/stage-goals", response_model=list[ProjectStageGoalRead])
def list_project_stage_goals(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ProjectStageGoalRead]:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    goals = db.scalars(
        select(ProjectStageGoal)
        .where(ProjectStageGoal.project_id == project_id)
        .order_by(ProjectStageGoal.status.asc(), ProjectStageGoal.due_at.asc(), ProjectStageGoal.id.desc())
    )
    return [_goal_with_progress(db, goal) for goal in goals]


@router.get("/{project_id}/stage-goals/{goal_id}/timeline", response_model=list[ProjectStageGoalTimelineItem])
def list_project_stage_goal_timeline(
    project_id: int,
    goal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ProjectStageGoalTimelineItem]:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    goal = _get_stage_goal_or_404(db, project_id, goal_id)
    items = [
        ProjectStageGoalTimelineItem(
            event_type="stage_goal.created",
            title=f"创建阶段目标：{goal.title}",
            message=goal.note,
            resource_type="project_stage_goal",
            resource_id=goal.id,
            status=goal.status,
            detail={"metric_key": goal.metric_key, "target_value": goal.target_value},
            created_at=goal.created_at,
        )
    ]
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(300)
    )
    for log in logs:
        if int(log.detail_json.get("stage_goal_id") or 0) != goal_id:
            continue
        resource_type = log.resource_type
        resource_id = log.resource_id
        if log.action == "stage_goal.action.generate_draft_and_review":
            resource_type = "article_draft"
            resource_id = int(log.detail_json.get("draft_id") or resource_id or 0) or resource_id
        items.append(
            ProjectStageGoalTimelineItem(
                event_type=log.action,
                title={
                    "stage_goal.action.run_crawl": "发起搜索采集",
                    "stage_goal.action.generate_draft_and_review": "生成稿件并完成 AI 评分",
                    "stage_goal.action.create_placement": "创建投放计划",
                    "stage_goal.action.create_delivery_followup": "创建交付跟进",
                    "stage_goal.action.approve_and_create_placement": "人工通过稿件并创建投放计划",
                    "stage_goal.action.publish_prepare_delivery": "发布投放并进入交付包",
                    "stage_goal.action.run_full_loop": "一键跑通 GEO 闭环",
                    "stage_goal.delivery_confirmed": "客户确认交付报告",
                }.get(log.action, log.action),
                message=None,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_url=_stage_goal_resource_url(project_id, resource_type, resource_id),
                status=None,
                detail=log.detail_json,
                created_at=log.created_at,
            )
        )
    alerts = db.scalars(
        select(SystemAlert)
        .where(SystemAlert.project_id == project_id)
        .order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
        .limit(300)
    )
    for alert in alerts:
        if int(alert.detail_json.get("stage_goal_id") or 0) != goal_id:
            continue
        items.append(
            ProjectStageGoalTimelineItem(
                event_type=alert.alert_type,
                title=alert.title,
                message=alert.message,
                resource_type="system_alert",
                resource_id=alert.id,
                resource_url="/admin/alerts",
                status=alert.status,
                detail=alert.detail_json,
                created_at=alert.created_at,
            )
        )
    return sorted(items, key=lambda item: item.created_at, reverse=True)


@router.post("/{project_id}/stage-goals", response_model=ProjectStageGoalRead, status_code=201)
def create_project_stage_goal(
    project_id: int,
    payload: ProjectStageGoalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> ProjectStageGoalRead:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    goal = ProjectStageGoal(project_id=project_id, **payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _goal_with_progress(db, goal)


@router.post("/{project_id}/stage-goals/reminders/run", response_model=list[SystemAlertRead], status_code=201)
def run_project_stage_goal_reminders(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "company_admin")),
) -> list[SystemAlert]:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    existing_alerts = list(
        db.scalars(
            select(SystemAlert).where(
                SystemAlert.project_id == project_id,
                SystemAlert.status.in_(["open", "acknowledged"]),
                SystemAlert.alert_type.in_(["stage_goal.overdue", "stage_goal.at_risk"]),
            )
        )
    )
    goals = list(
        db.scalars(
            select(ProjectStageGoal).where(
                ProjectStageGoal.project_id == project_id,
                ProjectStageGoal.status == "active",
            )
        )
    )
    created: list[SystemAlert] = []
    for goal in goals:
        goal_read = _goal_with_progress(db, goal)
        alert_type = None
        severity = "warning"
        if goal_read.risk_level == "overdue":
            alert_type = "stage_goal.overdue"
            severity = "critical"
        elif goal_read.risk_level == "at_risk":
            alert_type = "stage_goal.at_risk"
        if alert_type is None or _has_active_goal_alert(
            existing_alerts + created, alert_type=alert_type, goal_id=goal.id
        ):
            continue
        metric_name = METRIC_LABELS.get(goal.metric_key, goal.metric_key)
        alert = SystemAlert(
            company_id=project.company_id,
            project_id=project.id,
            alert_type=alert_type,
            severity=severity,
            status="open",
            title=f"阶段目标{'已逾期' if alert_type == 'stage_goal.overdue' else '存在风险'}：{goal.title}",
            message=goal_read.review_summary or f"{metric_name} 阶段目标需要跟进。",
            detail_json={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "metric_name": metric_name,
                "current_value": goal_read.current_value,
                "target_value": goal.target_value,
                "progress_rate": goal_read.progress_rate,
                "risk_level": goal_read.risk_level,
                "due_at": goal.due_at.isoformat() if goal.due_at else None,
                "recommendations": goal_read.recommendations,
            },
        )
        db.add(alert)
        db.flush()
        created.append(alert)
    db.commit()
    for alert in created:
        db.refresh(alert)
    return created


@router.post(
    "/{project_id}/stage-goals/{goal_id}/actions/{action_type}",
    response_model=ProjectStageGoalActionResult,
    status_code=201,
)
def run_project_stage_goal_action(
    project_id: int,
    goal_id: int,
    action_type: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> ProjectStageGoalActionResult:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    goal = _get_stage_goal_or_404(db, project_id, goal_id)
    topic = _goal_action_topic(goal)

    if action_type == "run_full_loop":
        task = create_crawl_task(
            db,
            project,
            CrawlTaskCreate(task_type="stage_goal_full_loop", schedule_type="manual", execute_now=True),
        )
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.run_crawl",
            resource_type="crawl_task",
            resource_id=task.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={"stage_goal_id": goal.id, "metric_key": goal.metric_key, "full_loop": True},
        )
        draft = generate_article_draft(
            db,
            project,
            ArticleDraftGenerate(
                topic=topic,
                draft_type="stage_goal_article",
                source_context=_goal_draft_source_context(goal, action_type),
            ),
        )
        ai_review = review_article_draft(db, draft, review_type="ai")
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.generate_draft_and_review",
            resource_type="article_review",
            resource_id=ai_review.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "draft_id": draft.id,
                "total_score": ai_review.total_score,
                "grade": ai_review.grade,
                "full_loop": True,
            },
        )
        human_review = decide_article_draft_review(
            db,
            draft,
            reviewer_id=user.id,
            decision="approved",
            comment="阶段目标一键闭环自动通过，进入投放计划。",
        )
        placement = PlacementRecord(
            project_id=project_id,
            article_draft_id=draft.id,
            channel=f"阶段目标投放：{METRIC_LABELS.get(goal.metric_key, goal.metric_key)}",
            status="published",
            published_at=utcnow(),
            visibility="customer_visible",
            delivery_status="ready",
            notes=f"由阶段目标“{goal.title}”的一键闭环生成。",
            archive_note=f"阶段目标“{goal.title}”已通过一键闭环发布并进入客户交付包。",
        )
        db.add(placement)
        db.flush()
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.approve_and_create_placement",
            resource_type="placement_record",
            resource_id=placement.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "draft_id": draft.id,
                "human_review_id": human_review.id,
                "placement_id": placement.id,
                "full_loop": True,
            },
        )
        review_alerts = create_placement_reminder_alerts(
            db,
            project_id=project_id,
            review_after_days=0,
        )
        related_alert = next(
            (
                alert
                for alert in review_alerts
                if int(alert.detail_json.get("placement_id") or 0) == placement.id
            ),
            None,
        )
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.publish_prepare_delivery",
            resource_type="placement_record",
            resource_id=placement.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "placement_id": placement.id,
                "review_alert_id": related_alert.id if related_alert else None,
                "review_crawl_task_id": related_alert.detail_json.get("review_crawl_task_id") if related_alert else None,
                "delivery_status": placement.delivery_status,
                "visibility": placement.visibility,
                "full_loop": True,
            },
        )
        share = DeliveryPackageShare(
            project_id=project_id,
            token=secrets.token_urlsafe(24),
            name=f"{goal.title} 客户交付包",
            status="active",
            created_by_user_id=user.id,
        )
        db.add(share)
        db.flush()
        goal_read = _goal_with_progress(db, goal)
        alert = SystemAlert(
            company_id=project.company_id,
            project_id=project.id,
            alert_type="stage_goal.delivery_followup",
            severity="info",
            status="open",
            title=f"阶段目标交付跟进：{goal.title}",
            message=goal_read.review_summary or "该阶段目标需要同步客户交付和下一步动作。",
            detail_json={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "current_value": goal_read.current_value,
                "target_value": goal.target_value,
                "recommendations": goal_read.recommendations,
                "share_id": share.id,
                "placement_id": placement.id,
                "full_loop": True,
            },
        )
        db.add(alert)
        db.flush()
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.create_delivery_followup",
            resource_type="system_alert",
            resource_id=alert.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "share_id": share.id,
                "placement_id": placement.id,
                "full_loop": True,
            },
        )
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.run_full_loop",
            resource_type="placement_record",
            resource_id=placement.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "task_id": task.id,
                "draft_id": draft.id,
                "ai_review_id": ai_review.id,
                "human_review_id": human_review.id,
                "placement_id": placement.id,
                "share_id": share.id,
            },
        )
        db.commit()
        db.refresh(placement)
        db.refresh(share)
        return ProjectStageGoalActionResult(
            action_type=action_type,
            status="created",
            message="已完成阶段目标一键闭环：采集、撰稿评分、人工通过、发布交付、分享链接和交付跟进已串联。",
            resource_type="placement_record",
            resource_id=placement.id,
            resource_url=f"/projects/{project_id}/delivery-package",
            detail={
                "task_id": task.id,
                "draft_id": draft.id,
                "ai_review_id": ai_review.id,
                "human_review_id": human_review.id,
                "placement_id": placement.id,
                "share_id": share.id,
                "share_token": share.token,
                "public_share_url": f"/share/delivery/{share.token}",
                "review_alert_id": related_alert.id if related_alert else None,
                "review_crawl_task_id": related_alert.detail_json.get("review_crawl_task_id") if related_alert else None,
                "delivery_followup_alert_id": alert.id,
            },
        )

    if action_type == "run_crawl":
        task = create_crawl_task(
            db,
            project,
            CrawlTaskCreate(task_type="stage_goal_action", schedule_type="manual", execute_now=True),
        )
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.run_crawl",
            resource_type="crawl_task",
            resource_id=task.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={"stage_goal_id": goal.id, "metric_key": goal.metric_key},
        )
        db.commit()
        return ProjectStageGoalActionResult(
            action_type=action_type,
            status="created",
            message="已基于阶段目标发起搜索采集任务。",
            resource_type="crawl_task",
            resource_id=task.id,
            resource_url=f"/projects/{project_id}/tasks/{task.id}",
            detail={"task_status": task.status},
        )

    if action_type == "generate_draft":
        draft = generate_article_draft(
            db,
            project,
            ArticleDraftGenerate(
                topic=topic,
                draft_type="stage_goal_article",
                source_context=_goal_draft_source_context(goal, action_type),
            ),
        )
        review = review_article_draft(db, draft, review_type="ai")
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.generate_draft_and_review",
            resource_type="article_review",
            resource_id=review.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "draft_id": draft.id,
                "total_score": review.total_score,
                "grade": review.grade,
            },
        )
        db.commit()
        return ProjectStageGoalActionResult(
            action_type=action_type,
            status="created",
            message="已基于阶段目标生成一篇 GEO 友好稿件，并完成 AI 审核评分。",
            resource_type="article_draft",
            resource_id=draft.id,
            resource_url=f"/projects/{project_id}/drafts/{draft.id}",
            detail={
                "draft_status": draft.status,
                "title": draft.title,
                "review_id": review.id,
                "review_score": review.total_score,
                "review_grade": review.grade,
                "review_status": review.status,
            },
        )

    if action_type == "create_placement":
        draft, asset = _latest_approved_content(db, project_id)
        if draft is None and asset is None:
            raise HTTPException(status_code=422, detail="No approved draft or content asset available for placement")
        placement = PlacementRecord(
            project_id=project_id,
            article_draft_id=draft.id if draft is not None else None,
            content_asset_id=asset.id if draft is None and asset is not None else None,
            channel=f"阶段目标投放：{METRIC_LABELS.get(goal.metric_key, goal.metric_key)}",
            status="planned",
            notes=f"由阶段目标“{goal.title}”生成。{goal.note or ''}".strip(),
        )
        db.add(placement)
        db.flush()
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.create_placement",
            resource_type="placement_record",
            resource_id=placement.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={"stage_goal_id": goal.id, "metric_key": goal.metric_key},
        )
        db.commit()
        db.refresh(placement)
        return ProjectStageGoalActionResult(
            action_type=action_type,
            status="created",
            message="已基于阶段目标创建 planned 投放计划。",
            resource_type="placement_record",
            resource_id=placement.id,
            resource_url=f"/projects/{project_id}/sources",
            detail={"placement_status": placement.status, "channel": placement.channel},
        )

    if action_type == "create_delivery_followup":
        goal_read = _goal_with_progress(db, goal)
        alert = SystemAlert(
            company_id=project.company_id,
            project_id=project.id,
            alert_type="stage_goal.delivery_followup",
            severity="info",
            status="open",
            title=f"阶段目标交付跟进：{goal.title}",
            message=goal_read.review_summary or "该阶段目标需要同步客户交付和下一步动作。",
            detail_json={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "current_value": goal_read.current_value,
                "target_value": goal.target_value,
                "recommendations": goal_read.recommendations,
            },
        )
        db.add(alert)
        db.flush()
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.create_delivery_followup",
            resource_type="system_alert",
            resource_id=alert.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={"stage_goal_id": goal.id, "metric_key": goal.metric_key},
        )
        db.commit()
        db.refresh(alert)
        return ProjectStageGoalActionResult(
            action_type=action_type,
            status="created",
            message="已创建阶段目标交付跟进事项。",
            resource_type="system_alert",
            resource_id=alert.id,
            resource_url="/admin/alerts",
            detail={"alert_type": alert.alert_type, "severity": alert.severity},
        )

    if action_type == "approve_and_create_placement":
        draft_id = _latest_stage_goal_draft_id(db, project_id, goal.id)
        if draft_id is None:
            raise HTTPException(status_code=422, detail="No stage-goal draft available to approve")
        draft = db.get(ArticleDraft, draft_id)
        if draft is None or draft.project_id != project_id:
            raise HTTPException(status_code=404, detail="Stage-goal draft not found")
        review = decide_article_draft_review(
            db,
            draft,
            reviewer_id=user.id,
            decision="approved",
            comment="阶段目标动作自动通过，进入投放计划。",
        )
        placement = PlacementRecord(
            project_id=project_id,
            article_draft_id=draft.id,
            channel=f"阶段目标投放：{METRIC_LABELS.get(goal.metric_key, goal.metric_key)}",
            status="planned",
            notes=f"由阶段目标“{goal.title}”的已通过稿件生成。",
        )
        db.add(placement)
        db.flush()
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.approve_and_create_placement",
            resource_type="placement_record",
            resource_id=placement.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "draft_id": draft.id,
                "human_review_id": review.id,
                "placement_id": placement.id,
            },
        )
        db.commit()
        db.refresh(placement)
        return ProjectStageGoalActionResult(
            action_type=action_type,
            status="created",
            message="已将阶段目标稿件人工通过，并创建 planned 投放计划。",
            resource_type="placement_record",
            resource_id=placement.id,
            resource_url=f"/projects/{project_id}/sources",
            detail={
                "draft_id": draft.id,
                "human_review_id": review.id,
                "placement_status": placement.status,
                "channel": placement.channel,
            },
        )

    if action_type == "publish_prepare_delivery":
        placement_id = _latest_stage_goal_placement_id(db, project_id, goal.id)
        if placement_id is None:
            raise HTTPException(status_code=422, detail="No stage-goal placement available to publish")
        placement = db.get(PlacementRecord, placement_id)
        if placement is None or placement.project_id != project_id:
            raise HTTPException(status_code=404, detail="Stage-goal placement not found")
        now = utcnow()
        placement.status = "published"
        placement.published_at = now
        placement.visibility = "customer_visible"
        placement.delivery_status = "ready"
        placement.archive_note = (
            placement.archive_note
            or f"阶段目标“{goal.title}”已发布并进入客户交付包，等待复盘与客户确认。"
        )
        db.flush()
        review_alerts = create_placement_reminder_alerts(
            db,
            project_id=project_id,
            review_after_days=0,
        )
        related_alert = next(
            (
                alert
                for alert in review_alerts
                if int(alert.detail_json.get("placement_id") or 0) == placement.id
            ),
            None,
        )
        record_audit_log(
            db,
            user=user,
            action="stage_goal.action.publish_prepare_delivery",
            resource_type="placement_record",
            resource_id=placement.id,
            project_id=project.id,
            company_id=project.company_id,
            detail={
                "stage_goal_id": goal.id,
                "metric_key": goal.metric_key,
                "placement_id": placement.id,
                "review_alert_id": related_alert.id if related_alert else None,
                "review_crawl_task_id": related_alert.detail_json.get("review_crawl_task_id") if related_alert else None,
                "delivery_status": placement.delivery_status,
                "visibility": placement.visibility,
            },
        )
        db.commit()
        db.refresh(placement)
        return ProjectStageGoalActionResult(
            action_type=action_type,
            status="created",
            message="已发布阶段目标投放，并进入客户交付包与复盘提醒流程。",
            resource_type="placement_record",
            resource_id=placement.id,
            resource_url=f"/projects/{project_id}/delivery-package",
            detail={
                "placement_status": placement.status,
                "published_at": placement.published_at.isoformat() if placement.published_at else None,
                "visibility": placement.visibility,
                "delivery_status": placement.delivery_status,
                "review_alert_id": related_alert.id if related_alert else None,
                "review_crawl_task_id": related_alert.detail_json.get("review_crawl_task_id") if related_alert else None,
            },
        )

    raise HTTPException(status_code=422, detail="Unsupported stage goal action type")


@router.patch("/{project_id}/stage-goals/{goal_id}", response_model=ProjectStageGoalRead)
def update_project_stage_goal(
    project_id: int,
    goal_id: int,
    payload: ProjectStageGoalUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> ProjectStageGoalRead:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    goal = _get_stage_goal_or_404(db, project_id, goal_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return _goal_with_progress(db, goal)


@router.delete("/{project_id}/stage-goals/{goal_id}", response_model=APIMessage)
def delete_project_stage_goal(
    project_id: int,
    goal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> APIMessage:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    goal = _get_stage_goal_or_404(db, project_id, goal_id)
    db.delete(goal)
    db.commit()
    return APIMessage(message="Stage goal deleted")


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
) -> Project:
    project = get_project_or_404(db, project_id)
    assert_company_access(user, project.company_id)
    if payload.company_id is not None:
        get_company_or_404(db, payload.company_id)
        assert_company_access(user, payload.company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", response_model=APIMessage)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _user: object = Depends(require_roles("super_admin")),
) -> APIMessage:
    project = get_project_or_404(db, project_id)
    db.delete(project)
    db.commit()
    return APIMessage(message="Project deleted")
