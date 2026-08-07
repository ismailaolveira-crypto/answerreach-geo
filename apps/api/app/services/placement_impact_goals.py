from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerAnalysis,
    CitationSource,
    CrawlResult,
    PlacementRecord,
    Project,
    ProjectStageGoal,
)


PLACEMENT_IMPACT_MARKER_PREFIX = "placement_impact_id="


def _due_in_days(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def _metric_window(db: Session, project_id: int, *, before: bool, baseline: datetime) -> dict[str, float | int]:
    op = CrawlResult.collected_at < baseline if before else CrawlResult.collected_at >= baseline
    total = (
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .where(CrawlResult.project_id == project_id)
            .where(op)
        )
        or 0
    )
    mentions = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(op)
            .where(AnswerAnalysis.company_mentioned.is_(True))
        )
        or 0
    )
    recommendations = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(op)
            .where(AnswerAnalysis.company_recommended.is_(True))
        )
        or 0
    )
    denominator = total or 1
    return {
        "total_answers": int(total),
        "company_mentions": int(mentions),
        "company_recommendations": int(recommendations),
        "company_mention_rate": round(mentions / denominator, 4),
        "company_recommendation_rate": round(recommendations / denominator, 4),
    }


def _source_after_appearances(db: Session, project_id: int, placement: PlacementRecord, baseline: datetime) -> int:
    if not placement.target_url:
        return 0
    from urllib.parse import urlparse

    source_domain = urlparse(placement.target_url).netloc
    if not source_domain:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(CitationSource)
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project_id)
            .where(CrawlResult.collected_at >= baseline)
            .where(CitationSource.source_domain == source_domain)
        )
        or 0
    )


def create_placement_impact_goals(
    db: Session, project: Project, placement: PlacementRecord
) -> list[ProjectStageGoal]:
    marker = f"{PLACEMENT_IMPACT_MARKER_PREFIX}{placement.id}"
    existing_notes = list(
        db.scalars(
            select(ProjectStageGoal.note)
            .where(ProjectStageGoal.project_id == project.id)
            .where(ProjectStageGoal.note.contains(marker))
        )
    )
    if existing_notes:
        return []

    baseline = placement.published_at or placement.created_at
    before = _metric_window(db, project.id, before=True, baseline=baseline)
    after = _metric_window(db, project.id, before=False, baseline=baseline)
    after_sample_size = int(after["total_answers"] or 0)
    mention_delta = float(after["company_mention_rate"]) - float(before["company_mention_rate"])
    recommendation_delta = float(after["company_recommendation_rate"]) - float(
        before["company_recommendation_rate"]
    )
    source_appearances = _source_after_appearances(db, project.id, placement, baseline)

    created: list[ProjectStageGoal] = []

    def add_goal(
        *,
        title: str,
        metric_key: str,
        target_value: float,
        baseline_value: float,
        due_days: int,
        owner: str,
        note_lines: list[str],
    ) -> None:
        goal = ProjectStageGoal(
            project_id=project.id,
            title=title,
            metric_key=metric_key,
            target_value=target_value,
            baseline_value=baseline_value,
            due_at=_due_in_days(due_days),
            owner=owner,
            status="active",
            note="\n".join(
                [
                    f"来源投放复盘：{placement.channel}，{marker}",
                    f"投放后样本：{after_sample_size}；提及率变化：{mention_delta:.0%}；推荐率变化：{recommendation_delta:.0%}",
                ]
                + note_lines
            ),
        )
        db.add(goal)
        created.append(goal)

    if after_sample_size < 5:
        add_goal(
            title=f"投放复盘：补采 {placement.channel} 后续样本",
            metric_key="answer_count",
            target_value=max(10, after_sample_size + 10),
            baseline_value=float(after_sample_size),
            due_days=7,
            owner="GEO 运营",
            note_lines=[
                "判断：投放后样本量不足，不能形成稳定结论。",
                "动作：围绕目标问题和关键词重新发起跨模型采集，并保留网页端观测证据。",
            ],
        )

    if mention_delta <= 0 or recommendation_delta <= 0:
        add_goal(
            title=f"投放复盘：补强 {placement.channel} 推荐理由内容",
            metric_key="approved_content_count",
            target_value=1,
            baseline_value=0,
            due_days=10,
            owner="内容运营",
            note_lines=[
                "判断：投放后提及率或推荐率暂未改善。",
                "动作：补充目标问题直答、案例、资质、对比理由和适用场景，完成 AI 评分与人工审核。",
            ],
        )

    if placement.target_url and source_appearances == 0:
        add_goal(
            title=f"投放复盘：检查 {placement.channel} 页面可抓取性",
            metric_key="published_placement_count",
            target_value=1,
            baseline_value=0,
            due_days=14,
            owner="投放运营",
            note_lines=[
                "判断：投放链接未在投放后 AI 答案信源中出现。",
                f"投放链接：{placement.target_url}",
                "动作：检查页面结构、可索引性、标题摘要、Schema/FAQ、正文信源表达，并必要时补投高权重信源。",
            ],
        )

    if placement.visibility != "customer_visible" or placement.delivery_status != "accepted":
        add_goal(
            title=f"投放复盘：完成 {placement.channel} 客户交付确认",
            metric_key="accepted_delivery_count",
            target_value=1,
            baseline_value=0,
            due_days=7,
            owner="项目负责人",
            note_lines=[
                f"当前可见范围：{placement.visibility}；交付状态：{placement.delivery_status}。",
                "动作：生成客户交付包、发送复盘报告，并推动客户确认。",
            ],
        )

    if not created:
        add_goal(
            title=f"投放复盘：扩展 {placement.channel} 相似选题",
            metric_key="recommendation_rate",
            target_value=min(1.0, float(after["company_recommendation_rate"]) + 0.05),
            baseline_value=float(after["company_recommendation_rate"]),
            due_days=14,
            owner="GEO 运营",
            note_lines=[
                "判断：投放后指标已有改善。",
                "动作：扩展相似目标问题和关键词，继续监测推荐率能否保持增长。",
            ],
        )

    if created:
        db.flush()
    return created
