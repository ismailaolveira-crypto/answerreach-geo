from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import CrawlSchedule, Project, TargetQuestion


PROJECT_ID = 1
PROVIDER_ID = 10
SAMPLE_RUNS_PER_PROMPT = 4

EVALUATION_QUESTIONS = [
    "春秋元泉 Token 统一管控平台有哪些核心能力？",
    "春秋元泉 Token 统一管控平台适合哪些企业使用？",
    "春秋元泉 Token 统一管控平台和 LiteLLM 相比有什么区别？",
    "春秋元泉 Token 统一管控平台和 Portkey 相比怎么选？",
    "春秋元泉 Token 统一管控平台和 Langfuse 相比有什么优势和不足？",
    "国内有哪些支持私有化部署的 Token 统一管控平台？",
    "政企采购大模型 API 治理平台时应重点评估哪些厂商？",
    "需要多模型统一接入、配额和成本分摊时应该选择什么产品？",
    "哪类平台能同时解决大模型 API 密钥、审计和 Token 成本治理？",
    "企业级 Token 统一管控平台的主流竞品有哪些？",
]


def main() -> None:
    with SessionLocal() as db:
        project = db.get(Project, PROJECT_ID)
        if project is None:
            raise RuntimeError(f"Project #{PROJECT_ID} not found")

        existing = {
            item.question_text: item
            for item in db.scalars(
                select(TargetQuestion).where(TargetQuestion.project_id == PROJECT_ID)
            )
        }
        next_priority = max((item.priority for item in existing.values()), default=0) + 1
        added = 0
        for question_text in EVALUATION_QUESTIONS:
            if question_text in existing:
                continue
            db.add(
                TargetQuestion(
                    project_id=PROJECT_ID,
                    question_text=question_text,
                    question_type="competitive_evaluation",
                    priority=next_priority,
                    status="active",
                )
            )
            next_priority += 1
            added += 1
        db.flush()

        question_ids = list(
            db.scalars(
                select(TargetQuestion.id)
                .where(TargetQuestion.project_id == PROJECT_ID, TargetQuestion.status == "active")
                .order_by(TargetQuestion.priority, TargetQuestion.id)
            )
        )
        if len(question_ids) != 25:
            raise RuntimeError(f"Expected 25 active questions, found {len(question_ids)}")

        schedule = db.scalar(
            select(CrawlSchedule)
            .where(CrawlSchedule.project_id == PROJECT_ID)
            .order_by(CrawlSchedule.id)
            .limit(1)
        )
        if schedule is None:
            schedule = CrawlSchedule(project_id=PROJECT_ID)
            db.add(schedule)
        schedule.name = "春秋元泉 Token 统一管控平台每周 100 次模型搜索评测"
        schedule.schedule_type = "weekly"
        schedule.interval_hours = 168
        schedule.provider_ids = [PROVIDER_ID]
        schedule.target_question_ids = question_ids
        schedule.keyword_ids = []
        schedule.sample_runs_per_prompt = SAMPLE_RUNS_PER_PROMPT
        schedule.status = "active"
        schedule.next_run_at = datetime.now(UTC) + timedelta(days=7)

        db.commit()
        print(
            {
                "project_id": PROJECT_ID,
                "questions_added": added,
                "active_question_count": len(question_ids),
                "provider_ids": schedule.provider_ids,
                "sample_runs_per_prompt": schedule.sample_runs_per_prompt,
                "planned_calls_per_run": len(question_ids)
                * len(schedule.provider_ids)
                * schedule.sample_runs_per_prompt,
                "schedule_type": schedule.schedule_type,
                "next_run_at": schedule.next_run_at.isoformat(),
            }
        )


if __name__ == "__main__":
    main()
