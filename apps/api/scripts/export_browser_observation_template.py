import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401
from app.db.session import Base, SessionLocal, engine
from app.models import AnswerAnalysis, CrawlResult, CrawlTask, Keyword, LLMProvider, Project, TargetQuestion


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "yuanquan_browser_observation_template.json"
DEFAULT_PLATFORMS = ["豆包", "DeepSeek", "Kimi", "千问"]


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _provider_platform(provider: LLMProvider) -> str:
    return str(provider.cost_rule.get("platform_name") or provider.name)


def _coverage_key(*, kind: str, item_id: int | None, platform: str | None) -> str | None:
    normalized_platform = str(platform or "").strip()
    if item_id is None or not normalized_platform:
        return None
    return f"{kind}:{item_id}:{normalized_platform}"


def _browser_observation_coverage(db, project_id: int) -> set[str]:
    rows = list(
        db.execute(
            select(CrawlResult, AnswerAnalysis)
            .join(CrawlTask, CrawlTask.id == CrawlResult.task_id)
            .join(AnswerAnalysis, AnswerAnalysis.crawl_result_id == CrawlResult.id, isouter=True)
            .where(CrawlResult.project_id == project_id)
            .where(CrawlResult.status == "success")
            .where(CrawlTask.task_type == "browser_observation_manual")
        )
    )
    coverage: set[str] = set()
    for result, analysis in rows:
        observation = {}
        if analysis is not None:
            observation = (analysis.analysis_json or {}).get("browser_observation") or {}
        platform = str(observation.get("platform_name") or "").strip()
        question_key = _coverage_key(kind="question", item_id=result.target_question_id, platform=platform)
        keyword_key = _coverage_key(kind="keyword", item_id=result.keyword_id, platform=platform)
        if question_key:
            coverage.add(question_key)
        if keyword_key:
            coverage.add(keyword_key)
    return coverage


def _missing_platforms(coverage: set[str], *, kind: str, item_id: int, platforms: list[str]) -> list[str]:
    return [platform for platform in platforms if f"{kind}:{item_id}:{platform}" not in coverage]


def export_browser_observation_template(
    *,
    project_id: int,
    output_path: Path,
    question_limit: int,
    keyword_limit: int,
    platforms: list[str],
) -> dict[str, Any]:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        _require(project is not None, "Project not found", project_id)
        providers = list(
            db.scalars(
                select(LLMProvider)
                .where(LLMProvider.provider_type == "browser_observation")
                .where(LLMProvider.status == "active")
                .order_by(LLMProvider.id.asc())
            )
        )
        provider_by_platform = {_provider_platform(provider): provider for provider in providers}
        missing_platforms = [platform for platform in platforms if platform not in provider_by_platform]
        _require(not missing_platforms, "Missing browser observation providers", missing_platforms)

        coverage = _browser_observation_coverage(db, project_id)

        all_questions = list(
            db.scalars(
                select(TargetQuestion)
                .where(TargetQuestion.project_id == project_id)
                .where(TargetQuestion.status == "active")
                .order_by(TargetQuestion.priority.asc(), TargetQuestion.id.asc())
            )
        )
        all_keywords = list(
            db.scalars(
                select(Keyword)
                .where(Keyword.project_id == project_id)
                .where(Keyword.status == "active")
                .order_by(Keyword.priority.asc(), Keyword.id.asc())
            )
        )
        question_targets = [
            (question, _missing_platforms(coverage, kind="question", item_id=question.id, platforms=platforms))
            for question in all_questions
        ]
        keyword_targets = [
            (keyword, _missing_platforms(coverage, kind="keyword", item_id=keyword.id, platforms=platforms))
            for keyword in all_keywords
        ]
        question_targets = [(question, missing) for question, missing in question_targets if missing][:question_limit]
        keyword_targets = [(keyword, missing) for keyword, missing in keyword_targets if missing][:keyword_limit]

        observations: list[dict[str, Any]] = []
        for question, missing_platforms_for_question in question_targets:
            for platform in missing_platforms_for_question:
                provider = provider_by_platform[platform]
                observations.append(
                    {
                        "platform_name": platform,
                        "provider_id": provider.id,
                        "target_question_id": question.id,
                        "keyword_id": None,
                        "prompt_text": question.question_text,
                        "raw_answer": "待填：粘贴该平台网页端返回的完整真实答案，保留推荐对象、判断依据和可见信源。",
                        "answer_summary": "待填：一句话概括该平台回答。",
                        "source_urls": [],
                        "evidence_filename": f"{platform}-question-{question.id}.png",
                        "screenshot_url": "",
                        "observation_url": provider.api_base_url,
                        "observer_name": "外部浏览器采集",
                        "note": "网页端人工观测，含截图留证。",
                    }
                )
        for keyword, missing_platforms_for_keyword in keyword_targets:
            prompt_text = f"{keyword.keyword} 相关服务商怎么选？"
            for platform in missing_platforms_for_keyword:
                provider = provider_by_platform[platform]
                observations.append(
                    {
                        "platform_name": platform,
                        "provider_id": provider.id,
                        "target_question_id": None,
                        "keyword_id": keyword.id,
                        "prompt_text": prompt_text,
                        "raw_answer": "待填：粘贴该平台网页端返回的完整真实答案，保留推荐对象、判断依据和可见信源。",
                        "answer_summary": "待填：一句话概括该平台回答。",
                        "source_urls": [],
                        "evidence_filename": f"{platform}-keyword-{keyword.id}.png",
                        "screenshot_url": "",
                        "observation_url": provider.api_base_url,
                        "observer_name": "外部浏览器采集",
                        "note": "网页端人工观测，含截图留证。",
                    }
                )

        output = {
            "project": {
                "id": project.id,
                "name": project.name,
                "target_industry": project.target_industry,
                "target_audience": project.target_audience,
            },
            "created_at": datetime.now(UTC).isoformat(),
            "coverage": {
                "existing_browser_observation_pairs": len(coverage),
                "selected_question_count": len(question_targets),
                "selected_keyword_count": len(keyword_targets),
                "selection_policy": "first_uncovered_question_keyword_by_priority",
            },
            "instructions": [
                "在外部浏览器打开 observation_url。",
                "复制 prompt_text 到对应平台提问。",
                "把完整答案填入 raw_answer。",
                "保存截图或录屏；推荐把文件放到同一个证据目录，并在 evidence_filename 填文件名。",
                "如果不使用 --evidence-dir，也可以把本地 file:// 路径或共享链接填入 screenshot_url。",
                "把页面可见信源填入 source_urls；如果没有可见信源，填空数组 []。",
                f"填完后先 dry-run 校验：scripts/import_browser_observations.py --project-id {project_id} --input 本文件 --evidence-dir 证据目录 --dry-run。",
                f"校验通过后运行：scripts/import_browser_observations.py --project-id {project_id} --input 本文件 --evidence-dir 证据目录 --generate-draft。",
            ],
            "observations": observations,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "output": str(output_path),
        "project_id": project_id,
        "question_limit": question_limit,
        "keyword_limit": keyword_limit,
        "platforms": platforms,
        "observation_count": len(observations),
        "existing_browser_observation_pairs": len(coverage),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a browser observation JSON template for external collection.")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--question-limit", type=int, default=1)
    parser.add_argument("--keyword-limit", type=int, default=0)
    parser.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS))
    args = parser.parse_args()
    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()]
    result = export_browser_observation_template(
        project_id=args.project_id,
        output_path=args.output,
        question_limit=args.question_limit,
        keyword_limit=args.keyword_limit,
        platforms=platforms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
