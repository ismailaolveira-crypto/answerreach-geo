import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
REPO_ROOT = Path(__file__).resolve().parents[1]

from sqlalchemy import select

from import_real_collection import import_collection

from app.db.session import SessionLocal
from app.models import ArticleDraft, ArticleReview, PlacementRecord, Project, TargetQuestion
from app.schemas.content import ArticleDraftGenerate
from app.schemas.report import MaturityReportCreate
from app.services.article_workflow import generate_article_draft, review_article_draft
from app.services.maturity_report import create_report_action_goals, generate_maturity_report


def run_cycle(
    *,
    project_id: int,
    question_ids: list[int],
    provider_ids: list[int] | None,
    output_dir: Path,
    draft_count: int,
) -> dict:
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(
            f"Output directory is not empty: {output_dir}. Use a fresh directory for each real collection cycle."
        )
    env = {
        "PROJECT_ID": str(project_id),
        "QUESTION_IDS": ",".join(str(item) for item in question_ids),
        "OUT_DIR": str(output_dir),
    }
    if provider_ids:
        env["PROVIDER_IDS"] = ",".join(str(item) for item in provider_ids)
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "collect_real_answers_curl.sh")],
        check=True,
        env={**os.environ, **env},
        cwd=REPO_ROOT,
    )

    import_result = import_collection(project_id, output_dir)
    if import_result["result_count"] == 0:
        return {
            "collection": import_result,
            "report_id": None,
            "report_score": None,
            "maturity_level": None,
            "action_goal_count": 0,
            "drafts": [],
            "output_dir": str(output_dir),
            "status": "failed",
            "error": "No successful real API responses were imported; skipped report and draft generation.",
        }
    created_drafts = []
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        report = generate_maturity_report(
            db,
            project,
            MaturityReportCreate(
                title="春秋元泉 GEO 成熟度评估报告 - 自动真实采集",
                report_period="自动真实采集周期",
            ),
        )
        goals = create_report_action_goals(db, project, report)
        questions = list(
            db.scalars(
                select(TargetQuestion)
                .where(TargetQuestion.project_id == project_id)
                .where(TargetQuestion.id.in_(question_ids))
                .order_by(TargetQuestion.id.asc())
            )
        )
        for question in questions[:draft_count]:
            draft = generate_article_draft(
                db,
                project,
                ArticleDraftGenerate(
                    target_question_id=question.id,
                    draft_type="faq_article",
                    source_context={
                        "source": "real_geo_cycle",
                        "source_report_id": report.id,
                        "crawl_task_id": import_result["task_id"],
                        "core_insight": "基于真实模型采集结果反哺稿件，用于补齐可被 AI 自然采信的公开内容。",
                    },
                ),
            )
            review = review_article_draft(db, draft, review_type="ai")
            placement = PlacementRecord(
                project_id=project_id,
                article_draft_id=draft.id,
                channel="官网 FAQ / 解决方案页",
                target_url=f"https://example.local/yuanquan/geo-draft-{draft.id}",
                status="planned",
                visibility="internal",
                delivery_status="not_delivered",
                notes=f"自动真实采集周期生成，待人工审核后投放。AI 评分 {review.total_score}/{review.grade}。来源报告 #{report.id}。",
            )
            db.add(placement)
            db.flush()
            created_drafts.append(
                {
                    "draft_id": draft.id,
                    "review_id": review.id,
                    "placement_id": placement.id,
                    "title": draft.title,
                    "score": review.total_score,
                    "grade": review.grade,
                }
            )
        db.commit()
        return {
            "collection": import_result,
            "report_id": report.id,
            "report_score": report.total_score,
            "maturity_level": report.maturity_level,
            "action_goal_count": len(goals),
            "drafts": created_drafts,
            "output_dir": str(output_dir),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one real GEO collection -> report -> draft cycle.")
    parser.add_argument("--project-id", type=int, default=1)
    parser.add_argument("--question-ids", default="1,2,4")
    parser.add_argument("--provider-ids", default="")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--draft-count", type=int, default=3)
    args = parser.parse_args()
    question_ids = [int(item) for item in args.question_ids.split(",") if item.strip()]
    provider_ids = [int(item) for item in args.provider_ids.split(",") if item.strip()] or None
    output_dir = args.output_dir or Path("outputs/real_collection") / f"cycle-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    result = run_cycle(
        project_id=args.project_id,
        question_ids=question_ids,
        provider_ids=provider_ids,
        output_dir=output_dir,
        draft_count=args.draft_count,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
