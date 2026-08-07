from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ContentAsset, ContentAssetReview, Project, ProjectStageGoal


REMEDIATION_MARKER_PREFIX = "content_asset_remediation_id="


def _latest_asset_review(db: Session, asset_id: int) -> ContentAssetReview | None:
    return db.scalar(
        select(ContentAssetReview)
        .where(ContentAssetReview.content_asset_id == asset_id)
        .order_by(ContentAssetReview.created_at.desc(), ContentAssetReview.id.desc())
        .limit(1)
    )


def _approved_content_count(db: Session, project_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ContentAsset)
            .where(ContentAsset.project_id == project_id)
            .where(ContentAsset.status == "approved")
        )
        or 0
    )


def create_content_asset_remediation_goals(
    db: Session,
    project: Project,
    *,
    max_assets: int = 10,
    score_threshold: int = 85,
) -> list[ProjectStageGoal]:
    assets = list(
        db.scalars(
            select(ContentAsset)
            .where(ContentAsset.project_id == project.id)
            .order_by(ContentAsset.updated_at.desc(), ContentAsset.id.desc())
        )
    )
    if not assets:
        return []

    existing_notes = list(
        db.scalars(
            select(ProjectStageGoal.note)
            .where(ProjectStageGoal.project_id == project.id)
            .where(ProjectStageGoal.note.contains(REMEDIATION_MARKER_PREFIX))
        )
    )
    existing_markers = {note for note in existing_notes if note}
    baseline = _approved_content_count(db, project.id)
    created: list[ProjectStageGoal] = []

    for asset in assets:
        marker = f"{REMEDIATION_MARKER_PREFIX}{asset.id}"
        if any(marker in note for note in existing_markers):
            continue
        latest_review = _latest_asset_review(db, asset.id)
        score = int(latest_review.total_score) if latest_review is not None else None
        needs_remediation = (
            latest_review is None
            or score is None
            or score < score_threshold
            or asset.status in {"needs_revision", "rejected", "draft"}
        )
        if not needs_remediation:
            continue
        reason = "尚未 AI 评分" if latest_review is None else f"最新评分 {score}，评级 {latest_review.grade}"
        top_suggestions = []
        if latest_review is not None:
            for item in (latest_review.issues_json or []) + (latest_review.suggestions_json or []):
                message = item.get("message") or item.get("title") or item.get("type")
                if message:
                    top_suggestions.append(str(message))
                if len(top_suggestions) >= 3:
                    break
        note_lines = [
            marker,
            f"来源内容资产：#{asset.id} {asset.title}",
            f"整改原因：{reason}",
            f"当前状态：{asset.status}",
            "建议动作：基于该历史内容重新生成 GEO 优化稿，补充可引用证据、FAQ 结构和投放信源。",
        ]
        if top_suggestions:
            note_lines.append("审核建议：" + "；".join(top_suggestions))
        goal = ProjectStageGoal(
            project_id=project.id,
            title=f"内容整改：{asset.title[:80]}",
            metric_key="approved_content_count",
            baseline_value=float(baseline),
            target_value=float(baseline + len(created) + 1),
            due_at=datetime.now(UTC) + timedelta(days=14),
            owner="content_operator",
            status="active",
            note="\n".join(note_lines),
        )
        db.add(goal)
        db.flush()
        created.append(goal)
        if len(created) >= max_assets:
            break
    return created
