from datetime import UTC, datetime
from datetime import timedelta
from io import BytesIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerAnalysis,
    CitationSource,
    Company,
    CrawlResult,
    CrawlTask,
    Keyword,
    LLMProvider,
    MaturityReport,
    MaturityScoreItem,
    MentionedEntity,
    Project,
    ProjectStageGoal,
    TargetQuestion,
)
from app.schemas.report import MaturityReportCreate
from app.services.crawl_runner import KEYWORD_PROMPT_VARIANT_COUNT
from app.services.report_templates import get_active_report_template, report_template_snapshot


def _level(score: int) -> str:
    if score >= 81:
        return "L5 行业权威"
    if score >= 61:
        return "L4 稳定推荐"
    if score >= 41:
        return "L3 可被识别"
    if score >= 21:
        return "L2 偶发可见"
    return "L1 不可见"


def _score_rate(rate: float, max_score: int) -> int:
    return min(max_score, round(rate * max_score))


def _report_evidence_samples(db: Session, project_id: int, limit: int = 12) -> list[dict]:
    rows = db.execute(
        select(
            CrawlResult.id,
            CrawlResult.task_id,
            CrawlResult.target_question_id,
            CrawlResult.keyword_id,
            CrawlResult.provider_id,
            CrawlResult.prompt_text,
            CrawlResult.answer_summary,
            CrawlResult.collected_at,
            LLMProvider.name.label("provider_name"),
            LLMProvider.provider_type,
            AnswerAnalysis.company_mentioned,
            AnswerAnalysis.company_recommended,
            AnswerAnalysis.company_rank,
            AnswerAnalysis.sentiment,
            AnswerAnalysis.confidence,
            AnswerAnalysis.analysis_json,
        )
        .outerjoin(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
        .outerjoin(AnswerAnalysis, AnswerAnalysis.crawl_result_id == CrawlResult.id)
        .where(CrawlResult.project_id == project_id)
        .order_by(
            AnswerAnalysis.company_recommended.desc().nullslast(),
            AnswerAnalysis.company_mentioned.desc().nullslast(),
            CrawlResult.collected_at.desc().nullslast(),
            CrawlResult.id.desc(),
        )
        .limit(limit)
    ).all()
    if not rows:
        return []
    result_ids = [row.id for row in rows]
    source_rows = db.execute(
        select(
            CitationSource.crawl_result_id,
            CitationSource.source_domain,
            CitationSource.source_url,
            CitationSource.source_title,
            CitationSource.is_owned,
            CitationSource.is_placed,
            CitationSource.ai_readiness_score,
        )
        .where(CitationSource.crawl_result_id.in_(result_ids))
        .order_by(CitationSource.ai_readiness_score.desc(), CitationSource.id.asc())
    ).all()
    sources_by_result: dict[int, list[dict]] = {}
    for source in source_rows:
        sources_by_result.setdefault(source.crawl_result_id, []).append(
            {
                "domain": source.source_domain,
                "url": source.source_url,
                "title": source.source_title,
                "is_owned": bool(source.is_owned),
                "is_placed": bool(source.is_placed),
                "ai_readiness_score": int(source.ai_readiness_score or 0),
            }
        )
    return [
        {
            "crawl_result_id": row.id,
            "task_id": row.task_id,
            "target_question_id": row.target_question_id,
            "keyword_id": row.keyword_id,
            "provider_id": row.provider_id,
            "provider_name": row.provider_name or "unknown",
            "provider_type": row.provider_type or "unknown",
            "prompt_text": row.prompt_text,
            "answer_summary": row.answer_summary,
            "company_mentioned": bool(row.company_mentioned),
            "company_recommended": bool(row.company_recommended),
            "company_rank": row.company_rank,
            "sentiment": row.sentiment,
            "confidence": int(row.confidence or 0),
            "manual_corrected": bool((row.analysis_json or {}).get("manual_correction")),
            "source_count": len(sources_by_result.get(row.id, [])),
            "top_sources": sources_by_result.get(row.id, [])[:3],
            "collected_at": row.collected_at.isoformat() if row.collected_at else None,
        }
        for row in rows
    ]


def _keyword_prompt_coverage(db: Session, project_id: int, sample_limit: int = 3) -> dict:
    keywords = list(
        db.scalars(select(Keyword).where(Keyword.project_id == project_id).order_by(Keyword.priority, Keyword.id))
    )
    items: list[dict] = []
    full_coverage_count = 0
    total_prompt_variants = 0
    for keyword in keywords:
        result_rows = db.execute(
            select(CrawlResult.prompt_text, CrawlResult.provider_id, CrawlResult.id)
            .where(CrawlResult.project_id == project_id, CrawlResult.keyword_id == keyword.id)
            .order_by(CrawlResult.collected_at.desc().nullslast(), CrawlResult.id.desc())
        ).all()
        prompts = list(dict.fromkeys(row.prompt_text for row in result_rows if row.prompt_text))
        provider_ids = {row.provider_id for row in result_rows if row.provider_id is not None}
        prompt_variant_count = len(prompts)
        total_prompt_variants += prompt_variant_count
        if prompt_variant_count >= KEYWORD_PROMPT_VARIANT_COUNT:
            full_coverage_count += 1
        items.append(
            {
                "keyword_id": keyword.id,
                "keyword": keyword.keyword,
                "prompt_variant_count": prompt_variant_count,
                "target_variant_count": KEYWORD_PROMPT_VARIANT_COUNT,
                "provider_count": len(provider_ids),
                "result_count": len(result_rows),
                "coverage_status": "complete" if prompt_variant_count >= KEYWORD_PROMPT_VARIANT_COUNT else "partial"
                if prompt_variant_count > 0
                else "missing",
                "sample_prompts": prompts[:sample_limit],
            }
        )
    keyword_count = len(keywords)
    return {
        "target_variant_count": KEYWORD_PROMPT_VARIANT_COUNT,
        "keyword_count": keyword_count,
        "full_coverage_count": full_coverage_count,
        "partial_coverage_count": sum(1 for item in items if item["coverage_status"] == "partial"),
        "missing_count": sum(1 for item in items if item["coverage_status"] == "missing"),
        "avg_prompt_variants_per_keyword": round(total_prompt_variants / (keyword_count or 1), 2),
        "coverage_rate": round(full_coverage_count / (keyword_count or 1), 4),
        "items": items,
    }


def _brand_visibility_matrix(db: Session, project: Project, company: Company | None) -> dict:
    provider_rows = db.execute(
        select(
            CrawlResult.provider_id,
            LLMProvider.name.label("provider_name"),
            LLMProvider.provider_type,
            func.count(CrawlResult.id).label("answer_count"),
            func.sum(func.coalesce(AnswerAnalysis.company_mentioned, 0)).label("company_mentions"),
            func.sum(func.coalesce(AnswerAnalysis.company_recommended, 0)).label("company_recommendations"),
            func.avg(AnswerAnalysis.company_rank).label("avg_company_rank"),
        )
        .outerjoin(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
        .outerjoin(AnswerAnalysis, AnswerAnalysis.crawl_result_id == CrawlResult.id)
        .where(CrawlResult.project_id == project.id)
        .group_by(CrawlResult.provider_id, LLMProvider.name, LLMProvider.provider_type)
        .order_by(func.count(CrawlResult.id).desc())
    ).all()
    entity_rows = db.execute(
        select(
            CrawlResult.provider_id,
            MentionedEntity.entity_name,
            MentionedEntity.is_company,
            MentionedEntity.is_competitor,
            func.count(func.distinct(MentionedEntity.crawl_result_id)).label("answer_mentions"),
            func.sum(MentionedEntity.mention_count).label("mention_count"),
            func.count(MentionedEntity.recommendation_rank).label("recommendation_count"),
            func.avg(MentionedEntity.recommendation_rank).label("avg_rank"),
        )
        .join(CrawlResult, CrawlResult.id == MentionedEntity.crawl_result_id)
        .where(CrawlResult.project_id == project.id)
        .group_by(
            CrawlResult.provider_id,
            MentionedEntity.entity_name,
            MentionedEntity.is_company,
            MentionedEntity.is_competitor,
        )
    ).all()

    by_provider_entities: dict[int | None, list[dict]] = {}
    summary_by_brand: dict[str, dict] = {}
    company_name = company.name if company else project.name

    if company:
        summary_by_brand[company_name] = {
            "name": company_name,
            "brand_type": "company",
            "answer_mentions": 0,
            "mention_count": 0,
            "recommendation_count": 0,
            "avg_rank_values": [],
            "provider_ids": set(),
        }

    for row in entity_rows:
        if row.is_company:
            continue
        brand_type = "company" if row.is_company else "competitor" if row.is_competitor else "other"
        item = {
            "name": row.entity_name,
            "brand_type": brand_type,
            "answer_mentions": int(row.answer_mentions or 0),
            "mention_count": int(row.mention_count or 0),
            "recommendation_count": int(row.recommendation_count or 0),
            "avg_rank": round(float(row.avg_rank), 2) if row.avg_rank is not None else None,
        }
        by_provider_entities.setdefault(row.provider_id, []).append(item)
        summary = summary_by_brand.setdefault(
            row.entity_name,
            {
                "name": row.entity_name,
                "brand_type": brand_type,
                "answer_mentions": 0,
                "mention_count": 0,
                "recommendation_count": 0,
                "avg_rank_values": [],
                "provider_ids": set(),
            },
        )
        if summary["brand_type"] == "other" and brand_type != "other":
            summary["brand_type"] = brand_type
        summary["answer_mentions"] += item["answer_mentions"]
        summary["mention_count"] += item["mention_count"]
        summary["recommendation_count"] += item["recommendation_count"]
        if item["avg_rank"] is not None:
            summary["avg_rank_values"].append(item["avg_rank"])
        summary["provider_ids"].add(row.provider_id)

    by_provider = []
    for row in provider_rows:
        answer_count = int(row.answer_count or 0)
        company_mentions = int(row.company_mentions or 0)
        company_recommendations = int(row.company_recommendations or 0)
        company_avg_rank = round(float(row.avg_company_rank), 2) if row.avg_company_rank is not None else None
        if company:
            summary = summary_by_brand.setdefault(
                company_name,
                {
                    "name": company_name,
                    "brand_type": "company",
                    "answer_mentions": 0,
                    "mention_count": 0,
                    "recommendation_count": 0,
                    "avg_rank_values": [],
                    "provider_ids": set(),
                },
            )
            summary["answer_mentions"] += company_mentions
            summary["mention_count"] += company_mentions
            summary["recommendation_count"] += company_recommendations
            if company_avg_rank is not None:
                summary["avg_rank_values"].append(company_avg_rank)
            if company_mentions or company_recommendations:
                summary["provider_ids"].add(row.provider_id)
        top_entities = sorted(
            by_provider_entities.get(row.provider_id, []),
            key=lambda item: (
                item["recommendation_count"],
                item["mention_count"],
                -1 * (item["avg_rank"] or 999),
            ),
            reverse=True,
        )[:6]
        by_provider.append(
            {
                "provider_id": row.provider_id,
                "provider_name": row.provider_name or "unknown",
                "provider_type": row.provider_type or "unknown",
                "answer_count": answer_count,
                "company_mentions": company_mentions,
                "company_recommendations": company_recommendations,
                "company_mention_rate": round(company_mentions / (answer_count or 1), 4),
                "company_recommendation_rate": round(company_recommendations / (answer_count or 1), 4),
                "company_avg_rank": company_avg_rank,
                "top_entities": top_entities,
            }
        )

    summary = []
    for item in summary_by_brand.values():
        avg_rank_values = item.pop("avg_rank_values")
        provider_ids = item.pop("provider_ids")
        summary.append(
            {
                **item,
                "avg_rank": round(sum(avg_rank_values) / len(avg_rank_values), 2) if avg_rank_values else None,
                "provider_count": len(provider_ids),
            }
        )
    summary.sort(
        key=lambda item: (
            1 if item["brand_type"] == "company" else 0,
            item["recommendation_count"],
            item["mention_count"],
            -1 * (item["avg_rank"] or 999),
        ),
        reverse=True,
    )
    competitors = [item for item in summary if item["brand_type"] == "competitor"]
    company_item = next((item for item in summary if item["brand_type"] == "company"), None)
    leader = summary[0] if summary else None
    company_position = next((index + 1 for index, item in enumerate(summary) if item["brand_type"] == "company"), None)

    return {
        "company_name": company_name,
        "leader_name": leader["name"] if leader else None,
        "company_position": company_position,
        "competitor_count": len(competitors),
        "summary": summary[:12],
        "by_provider": by_provider,
        "objective_notes": [
            "按实际答案解析和实体推荐位聚合，不手工抬高企业排名。",
            "company_recommendations 来自答案解析；竞品 recommendation_count 来自实体推荐位。",
            "同一品牌跨模型出现越多，说明 AI 认知越稳定。",
        ],
        "company": company_item,
        "top_competitor": competitors[0] if competitors else None,
    }


def _delivery_readiness(
    *,
    total_answers: int,
    provider_count: int,
    question_coverage_rate: float,
    keyword_coverage_rate: float,
    evidence_samples: list[dict],
    evidence_source_mix: dict,
    brand_visibility_matrix: dict,
    recommendations: list[str],
    source_count: int,
) -> dict:
    checks = [
        {
            "key": "sample_size",
            "label": "样本量",
            "ok": total_answers >= 10,
            "current": total_answers,
            "required": 10,
            "weight": 15,
            "fix": "至少补齐 10 条 AI 答案样本；正式客户报告建议覆盖 10 个目标问题和 10 个关键词。",
        },
        {
            "key": "real_model_samples",
            "label": "真实模型样本",
            "ok": int(evidence_source_mix.get("real_api_sample_count", 0)) >= 1
            and int(evidence_source_mix.get("real_provider_count", 0)) >= 1,
            "current": int(evidence_source_mix.get("real_api_sample_count", 0)),
            "required": 1,
            "weight": 10,
            "fix": "至少补齐 1 条真实大模型 API 采集样本；Mock 样本只能证明系统闭环，不能作为正式客户报告的实采证据。",
        },
        {
            "key": "provider_coverage",
            "label": "模型覆盖",
            "ok": provider_count >= 3,
            "current": provider_count,
            "required": 3,
            "weight": 15,
            "fix": "至少使用 3 个模型渠道交叉采集，避免单模型偏差。",
        },
        {
            "key": "question_coverage",
            "label": "目标问题覆盖",
            "ok": question_coverage_rate >= 0.6,
            "current": round(question_coverage_rate, 4),
            "required": 0.6,
            "weight": 15,
            "fix": "补跑未覆盖的目标问题，确保报告覆盖客户最关心的业务问题。",
        },
        {
            "key": "keyword_coverage",
            "label": "关键词覆盖",
            "ok": keyword_coverage_rate >= 0.6,
            "current": round(keyword_coverage_rate, 4),
            "required": 0.6,
            "weight": 10,
            "fix": "按关键词分批补采，降低真实模型调用成本并补齐搜索语境。",
        },
        {
            "key": "evidence_traceability",
            "label": "证据可追溯",
            "ok": len(evidence_samples) >= min(5, total_answers) and source_count > 0,
            "current": len(evidence_samples),
            "required": min(5, total_answers) if total_answers else 1,
            "weight": 10,
            "fix": "补充可追溯答案样本和信源 URL，让每个结论能回到原始答案。",
        },
        {
            "key": "browser_or_screenshot_evidence",
            "label": "网页端/截图留证",
            "ok": bool(
                evidence_source_mix.get("browser_observation_count", 0)
                or evidence_source_mix.get("screenshot_evidence_count", 0)
            ),
            "current": int(evidence_source_mix.get("browser_observation_count", 0))
            + int(evidence_source_mix.get("screenshot_evidence_count", 0)),
            "required": 1,
            "weight": 10,
            "fix": "对关键问题做至少 1 条网页端观测或截图留证，校验 API 采集与真实产品界面表现。",
        },
        {
            "key": "brand_matrix",
            "label": "品牌推荐矩阵",
            "ok": bool(brand_visibility_matrix.get("summary") and brand_visibility_matrix.get("by_provider")),
            "current": len(brand_visibility_matrix.get("summary") or []),
            "required": 1,
            "weight": 10,
            "fix": "补充答案解析或人工校正，形成企业和竞品在各模型中的推荐矩阵。",
        },
        {
            "key": "actionable_recommendations",
            "label": "可执行建议",
            "ok": len(recommendations) >= 3,
            "current": len(recommendations),
            "required": 3,
            "weight": 5,
            "fix": "补充内容、信源、采集和投放四类优化建议，避免报告只有诊断没有行动。",
        },
    ]
    score = sum(item["weight"] for item in checks if item["ok"])
    blocker_count = sum(1 for item in checks if not item["ok"])
    status = "ready" if score >= 85 and blocker_count == 0 else "needs_review" if score >= 60 else "not_ready"
    return {
        "status": status,
        "score": score,
        "blocker_count": blocker_count,
        "checks": checks,
        "missing_actions": [item["fix"] for item in checks if not item["ok"]],
        "summary": (
            "报告已达到客户交付门槛。"
            if status == "ready"
            else "报告可内部评审，但建议补齐关键证据后再发客户。"
            if status == "needs_review"
            else "报告证据不足，暂不建议作为正式客户交付件。"
        ),
    }


def _due_in_days(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def create_report_action_goals(db: Session, project: Project, report: MaturityReport) -> list[ProjectStageGoal]:
    data = report.report_json or {}
    marker = f"report_id={report.id}"
    observation_marker = f"report_observation_id={report.id}"
    delivery_marker = f"report_delivery_readiness_id={report.id}"
    existing_goals = list(
        db.scalars(select(ProjectStageGoal).where(ProjectStageGoal.project_id == project.id))
    )
    has_report_actions = any(marker in (goal.note or "") for goal in existing_goals)
    has_observation_goal = any(observation_marker in (goal.note or "") for goal in existing_goals)
    has_delivery_goal = any(delivery_marker in (goal.note or "") for goal in existing_goals)

    topics = data.get("next_content_topics") or []
    question_gaps = data.get("question_gaps") or []
    keyword_gaps = data.get("keyword_gaps") or []
    source_gaps = data.get("source_gaps") or []
    coverage = data.get("coverage") or {}
    metrics = data.get("metrics") or {}
    evidence_quality = data.get("evidence_quality") or {}
    delivery_readiness = data.get("delivery_readiness") or {}
    delivery_checks = delivery_readiness.get("checks") or []
    missing_delivery_checks = [item for item in delivery_checks if not item.get("ok")]
    created: list[ProjectStageGoal] = []

    def add_goal(**kwargs) -> None:
        goal = ProjectStageGoal(project_id=project.id, **kwargs)
        db.add(goal)
        created.append(goal)

    if not has_report_actions and topics:
        add_goal(
            title=f"报告行动：产出 {min(3, len(topics))} 篇 GEO 优化内容",
            metric_key="approved_content_count",
            target_value=min(3, len(topics)),
            baseline_value=0,
            due_at=_due_in_days(14),
            owner="内容运营",
            status="active",
            note="\n".join(
                [f"来源报告 {report.title}，{marker}", "推荐选题："]
                + [f"- {item}" for item in topics[:3]]
            ),
        )

    if question_gaps or keyword_gaps:
        observation_prompts = (
            [item.get("question_text") for item in question_gaps]
            + [f"{item.get('keyword')} 相关服务商怎么选？" for item in keyword_gaps]
        )[:6]
        observation_prompts = [item for item in observation_prompts if item]
        if not has_report_actions:
            add_goal(
                title="报告行动：补齐目标问题与关键词采集覆盖",
                metric_key="answer_count",
                target_value=max(10, (len(question_gaps) + len(keyword_gaps)) * 2),
                baseline_value=float(coverage.get("sample_size") or metrics.get("total_answers") or 0),
                due_at=_due_in_days(7),
                owner="GEO 运营",
                status="active",
                note="\n".join(
                    [f"来源报告 {report.title}，{marker}", "问题缺口："]
                    + [f"- {item.get('question_text')}" for item in question_gaps[:5]]
                    + ["关键词缺口："]
                    + [f"- {item.get('keyword')}" for item in keyword_gaps[:5]]
                ),
            )
        if not has_observation_goal:
            current_observation_count = float(evidence_quality.get("browser_observation_count") or 0)
            add_goal(
                title=f"报告行动：完成 {max(1, len(observation_prompts))} 条网页端观测留证",
                metric_key="browser_observation_count",
                target_value=current_observation_count + max(1, len(observation_prompts)),
                baseline_value=current_observation_count,
                due_at=_due_in_days(7),
                owner="GEO 运营",
                status="active",
                note="\n".join(
                    [f"来源报告 {report.title}，{marker}，{observation_marker}", "网页端观测 Prompt："]
                    + [f"- {item}" for item in observation_prompts]
                    + ["执行要求：在豆包、DeepSeek、元宝、Kimi 等网页端抽样搜索，录入原始答案、截图/录屏地址和页面可见信源。"]
                ),
            )

    if not has_report_actions and source_gaps:
        add_goal(
            title="报告行动：补齐高价值信源投放",
            metric_key="published_placement_count",
            target_value=min(3, len(source_gaps)),
            baseline_value=0,
            due_at=_due_in_days(21),
            owner="投放运营",
            status="active",
            note="\n".join(
                [f"来源报告 {report.title}，{marker}", "优先处理信源："]
                + [
                    f"- {item.get('domain') or item.get('url') or '未知信源'}：{item.get('reason')}"
                    for item in source_gaps[:5]
                ]
            ),
        )

    if not has_delivery_goal and delivery_readiness.get("status") != "ready" and missing_delivery_checks:
        readiness_score = float(delivery_readiness.get("score") or 0)
        add_goal(
            title="报告行动：补齐客户交付质量门槛",
            metric_key="maturity_score",
            target_value=max(float(report.total_score + 5), 70),
            baseline_value=float(report.total_score),
            due_at=_due_in_days(10),
            owner="项目负责人",
            status="active",
            note="\n".join(
                [
                    f"来源报告 {report.title}，{marker}，{delivery_marker}",
                    f"当前交付就绪度：{delivery_readiness.get('status')}，{readiness_score:.0f}/100",
                    "待补质量项：",
                ]
                + [
                    f"- {item.get('label')}：当前 {item.get('current')} / 要求 {item.get('required')}；{item.get('fix')}"
                    for item in missing_delivery_checks[:8]
                ]
            ),
        )

    if not has_report_actions and not created:
        add_goal(
            title="报告行动：复盘本轮 GEO 成熟度报告",
            metric_key="health_score",
            target_value=max(70, report.total_score + 5),
            baseline_value=report.total_score,
            due_at=_due_in_days(14),
            owner="项目负责人",
            status="active",
            note=f"来源报告 {report.title}，{marker}\n暂无明显缺口，请围绕报告建议做复盘并规划下一轮监测。",
        )

    if created:
        db.flush()
    return created


def generate_maturity_report(
    db: Session, project: Project, payload: MaturityReportCreate
) -> MaturityReport:
    template = get_active_report_template(db)
    template_snapshot = report_template_snapshot(template)
    company = db.get(Company, project.company_id)
    total_answers = (
        db.scalar(select(func.count()).select_from(CrawlResult).where(CrawlResult.project_id == project.id))
        or 0
    )
    company_mentions = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(AnswerAnalysis.company_mentioned.is_(True))
        )
        or 0
    )
    company_recommendations = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(AnswerAnalysis.company_recommended.is_(True))
        )
        or 0
    )
    competitor_mentions = (
        db.scalar(
            select(func.count())
            .select_from(MentionedEntity)
            .join(CrawlResult, CrawlResult.id == MentionedEntity.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(MentionedEntity.is_competitor.is_(True))
        )
        or 0
    )
    source_count = (
        db.scalar(
            select(func.count())
            .select_from(CitationSource)
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
        )
        or 0
    )
    owned_source_count = (
        db.scalar(
            select(func.count())
            .select_from(CitationSource)
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(CitationSource.is_owned.is_(True))
        )
        or 0
    )
    placed_source_count = (
        db.scalar(
            select(func.count())
            .select_from(CitationSource)
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(CitationSource.is_placed.is_(True))
        )
        or 0
    )
    avg_crawlable_score = (
        db.scalar(
            select(func.avg(CitationSource.crawlable_score))
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
        )
        or 0
    )
    avg_ai_readiness_score = (
        db.scalar(
            select(func.avg(CitationSource.ai_readiness_score))
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
        )
        or 0
    )
    avg_confidence = (
        db.scalar(
            select(func.avg(AnswerAnalysis.confidence))
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
        )
        or 0
    )
    positive_answers = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(AnswerAnalysis.sentiment == "positive")
        )
        or 0
    )
    avg_company_rank = db.scalar(
        select(func.avg(AnswerAnalysis.company_rank))
        .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
        .where(CrawlResult.project_id == project.id)
        .where(AnswerAnalysis.company_rank.is_not(None))
    )
    target_question_count = (
        db.scalar(select(func.count()).select_from(TargetQuestion).where(TargetQuestion.project_id == project.id))
        or 0
    )
    keyword_count = (
        db.scalar(select(func.count()).select_from(Keyword).where(Keyword.project_id == project.id)) or 0
    )
    covered_question_count = (
        db.scalar(
            select(func.count(func.distinct(CrawlResult.target_question_id)))
            .where(CrawlResult.project_id == project.id)
            .where(CrawlResult.target_question_id.is_not(None))
        )
        or 0
    )
    covered_keyword_count = (
        db.scalar(
            select(func.count(func.distinct(CrawlResult.keyword_id)))
            .where(CrawlResult.project_id == project.id)
            .where(CrawlResult.keyword_id.is_not(None))
        )
        or 0
    )
    provider_count = (
        db.scalar(select(func.count(func.distinct(CrawlResult.provider_id))).where(CrawlResult.project_id == project.id))
        or 0
    )
    browser_observation_count = (
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .join(CrawlTask, CrawlTask.id == CrawlResult.task_id)
            .where(CrawlResult.project_id == project.id)
            .where(CrawlTask.task_type == "browser_observation_manual")
        )
        or 0
    )
    screenshot_evidence_count = (
        db.scalar(
            select(func.count())
            .select_from(CitationSource)
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(CitationSource.source_type == "screenshot")
        )
        or 0
    )
    browser_observation_platforms = sorted(
        {
            str(platform_name).strip()
            for platform_name in db.scalars(
                select(AnswerAnalysis.analysis_json["browser_observation"]["platform_name"].as_string())
                .select_from(AnswerAnalysis)
                .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
                .join(CrawlTask, CrawlTask.id == CrawlResult.task_id)
                .where(CrawlResult.project_id == project.id)
                .where(CrawlTask.task_type == "browser_observation_manual")
            )
            if platform_name and str(platform_name).strip()
        }
    )
    api_sample_count = max(0, total_answers - browser_observation_count)
    real_api_sample_count = (
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .outerjoin(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
            .where(CrawlResult.project_id == project.id)
            .where(func.coalesce(LLMProvider.provider_type, "unknown").not_in(["mock", "browser_observation"]))
        )
        or 0
    )
    mock_sample_count = (
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .outerjoin(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
            .where(CrawlResult.project_id == project.id)
            .where(LLMProvider.provider_type == "mock")
        )
        or 0
    )
    real_provider_count = (
        db.scalar(
            select(func.count(func.distinct(CrawlResult.provider_id)))
            .select_from(CrawlResult)
            .outerjoin(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
            .where(CrawlResult.project_id == project.id)
            .where(func.coalesce(LLMProvider.provider_type, "unknown").not_in(["mock", "browser_observation"]))
        )
        or 0
    )
    manual_correction_count = (
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(CrawlResult.project_id == project.id)
            .where(AnswerAnalysis.analysis_json["manual_correction"].is_not(None))
        )
        or 0
    )

    denominator = total_answers or 1
    mention_rate = company_mentions / denominator
    recommendation_rate = company_recommendations / denominator
    competitor_pressure = competitor_mentions / denominator
    owned_source_rate = owned_source_count / (source_count or 1)
    placed_source_rate = placed_source_count / (source_count or 1)
    positive_rate = positive_answers / denominator
    question_coverage_rate = covered_question_count / (target_question_count or 1)
    keyword_coverage_rate = covered_keyword_count / (keyword_count or 1)
    sample_confidence_score = min(100, round((avg_confidence or 0) * min(1, total_answers / 10)))
    evidence_samples = _report_evidence_samples(db, project.id)
    keyword_prompt_coverage = _keyword_prompt_coverage(db, project.id)
    brand_visibility_matrix = _brand_visibility_matrix(db, project, company)
    supporting_result_ids = [item["crawl_result_id"] for item in evidence_samples]
    evidence_source_mix = {
        "api_sample_count": api_sample_count,
        "real_api_sample_count": real_api_sample_count,
        "mock_sample_count": mock_sample_count,
        "browser_observation_count": browser_observation_count,
        "browser_observation_platform_count": len(browser_observation_platforms),
        "browser_observation_platforms": browser_observation_platforms,
        "screenshot_evidence_count": screenshot_evidence_count,
        "real_provider_count": real_provider_count,
        "real_sample_rate": round(real_api_sample_count / denominator, 4),
        "mock_sample_rate": round(mock_sample_count / denominator, 4),
        "browser_observation_rate": round(browser_observation_count / denominator, 4),
        "manual_correction_count": manual_correction_count,
        "manual_correction_rate": round(manual_correction_count / denominator, 4),
    }

    visibility_score = _score_rate(mention_rate, 20)
    recommendation_score = _score_rate(recommendation_rate, 20)
    competitor_score = max(0, 15 - _score_rate(competitor_pressure, 15))
    source_score = (
        round((owned_source_rate * 5) + (placed_source_rate * 5) + ((avg_ai_readiness_score or 0) / 100 * 5))
        if source_count
        else 5
    )
    content_score = 8 if total_answers else 3
    coverage_score = 10 if total_answers >= 10 else min(10, total_answers)
    risk_score = 5
    score_items_data = [
        ("AI 可见度", visibility_score, 20, f"企业在 {company_mentions}/{total_answers} 条答案中被提及。", ["mention_rate", "company_mentions"]),
        (
            "AI 推荐度",
            recommendation_score,
            20,
            f"企业在 {company_recommendations}/{total_answers} 条答案中被明确推荐或列为候选。",
            ["recommendation_rate", "company_recommendations"],
        ),
        ("竞品竞争力", competitor_score, 15, f"竞品相关提及 {competitor_mentions} 次。", ["competitor_pressure"]),
        ("信源健康度", source_score, 15, f"识别到信源 {source_count} 个，自有信源 {owned_source_count} 个。", ["source_count", "owned_source_rate", "placed_source_rate"]),
        ("内容资产成熟度", content_score, 15, "基于当前答案表现估算内容资产成熟度。", ["total_answers", "source_count"]),
        ("问题覆盖度", coverage_score, 10, f"当前采集样本量为 {total_answers}。", ["total_answers", "question_coverage_rate", "keyword_coverage_rate"]),
        ("风险可控性", risk_score, 5, "第一版尚未识别明显负面风险。", ["positive_rate", "avg_confidence"]),
    ]
    total_score = sum(item[1] for item in score_items_data)
    template_dimensions = (template_snapshot.get("scoring") or {}).get("dimensions") or []
    actual_dimension_names = {item[0] for item in score_items_data}
    matched_template_dimensions = [
        item for item in template_dimensions if item.get("name") in actual_dimension_names
    ]
    unmatched_template_dimensions = [
        item for item in template_dimensions if item.get("name") not in actual_dimension_names
    ]
    template_score_alignment = {
        "template_dimension_count": len(template_dimensions),
        "actual_dimension_count": len(score_items_data),
        "matched_dimension_count": len(matched_template_dimensions),
        "unmatched_template_dimensions": [
            {
                "key": item.get("key"),
                "name": item.get("name"),
                "max_score": item.get("max_score"),
            }
            for item in unmatched_template_dimensions
        ],
        "actual_dimensions": [
            {"name": dimension, "score": score, "max_score": max_score}
            for dimension, score, max_score, _explanation, _metric_keys in score_items_data
        ],
    }

    top_competitors = db.execute(
        select(MentionedEntity.entity_name, func.sum(MentionedEntity.mention_count).label("mentions"))
        .join(CrawlResult, CrawlResult.id == MentionedEntity.crawl_result_id)
        .where(CrawlResult.project_id == project.id)
        .where(MentionedEntity.is_competitor.is_(True))
        .group_by(MentionedEntity.entity_name)
        .order_by(func.sum(MentionedEntity.mention_count).desc())
        .limit(8)
    ).all()
    provider_breakdown = db.execute(
        select(
            CrawlResult.provider_id,
            LLMProvider.name,
            LLMProvider.provider_type,
            func.count(CrawlResult.id).label("answer_count"),
        )
        .outerjoin(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
        .where(CrawlResult.project_id == project.id)
        .group_by(CrawlResult.provider_id, LLMProvider.name, LLMProvider.provider_type)
        .order_by(func.count(CrawlResult.id).desc())
    ).all()
    top_sources = db.execute(
        select(
            CitationSource.source_domain,
            CitationSource.source_url,
            func.count(CitationSource.id).label("mentions"),
            func.max(CitationSource.is_owned).label("is_owned"),
            func.max(CitationSource.is_placed).label("is_placed"),
            func.max(CitationSource.ai_readiness_score).label("ai_readiness_score"),
        )
        .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
        .where(CrawlResult.project_id == project.id)
        .group_by(CitationSource.source_domain, CitationSource.source_url)
        .order_by(func.count(CitationSource.id).desc())
        .limit(10)
    ).all()
    question_gaps = db.execute(
        select(TargetQuestion.id, TargetQuestion.question_text)
        .where(TargetQuestion.project_id == project.id)
        .where(
            TargetQuestion.id.not_in(
                select(CrawlResult.target_question_id)
                .where(CrawlResult.project_id == project.id)
                .where(CrawlResult.target_question_id.is_not(None))
            )
        )
        .limit(8)
    ).all()
    keyword_gaps = db.execute(
        select(Keyword.id, Keyword.keyword)
        .where(Keyword.project_id == project.id)
        .where(
            Keyword.id.not_in(
                select(CrawlResult.keyword_id)
                .where(CrawlResult.project_id == project.id)
                .where(CrawlResult.keyword_id.is_not(None))
            )
        )
        .limit(8)
    ).all()

    recommendations = [
        "优先补齐能直接回答目标问题的官网 FAQ 和解决方案页。",
        "为高价值关键词生产结构化案例稿，包含适用场景、客户问题、解决路径和结果。",
        "将已有稿件改写为更适合 AI 摘录的定义句、列表句和结论句。",
        "持续监控竞品高频出现的问题，反向补内容缺口。",
    ]
    if total_answers < 10:
        recommendations.append("当前样本量偏小，建议至少覆盖 10 个目标问题、10 个关键词和 3 个以上模型渠道。")
    if provider_count < 3:
        recommendations.append("当前模型覆盖不足，建议接入 Kimi、豆包/方舟、千问等真实联网或兼容渠道交叉验证。")
    if owned_source_rate < 0.3:
        recommendations.append("自有信源占比较低，建议把官网、FAQ、案例页和媒体稿打造成更容易被 AI 采信的稳定来源。")
    if question_gaps:
        recommendations.append("仍有目标问题没有采集样本，建议补跑缺口问题后再生成正式客户报告。")
    if keyword_gaps:
        recommendations.append("仍有关键词没有采集样本，建议按关键词分批补跑，降低真实模型调用成本并补齐覆盖。")
    delivery_readiness = _delivery_readiness(
        total_answers=total_answers,
        provider_count=provider_count,
        question_coverage_rate=question_coverage_rate,
        keyword_coverage_rate=keyword_coverage_rate,
        evidence_samples=evidence_samples,
        evidence_source_mix=evidence_source_mix,
        brand_visibility_matrix=brand_visibility_matrix,
        recommendations=recommendations,
        source_count=source_count,
    )

    report_json = {
        "company": company.name if company else None,
        "project": project.name,
        "metrics": {
            "total_answers": total_answers,
            "company_mentions": company_mentions,
            "company_recommendations": company_recommendations,
            "mention_rate": round(mention_rate, 4),
            "recommendation_rate": round(recommendation_rate, 4),
            "competitor_pressure": round(competitor_pressure, 4),
            "source_count": source_count,
            "owned_source_count": owned_source_count,
            "owned_source_rate": round(owned_source_rate, 4),
            "placed_source_count": placed_source_count,
            "placed_source_rate": round(placed_source_rate, 4),
            "avg_crawlable_score": round(float(avg_crawlable_score or 0), 2),
            "avg_ai_readiness_score": round(float(avg_ai_readiness_score or 0), 2),
            "avg_confidence": round(float(avg_confidence or 0), 2),
            "sample_confidence_score": sample_confidence_score,
            "positive_answers": positive_answers,
            "positive_rate": round(positive_rate, 4),
            "avg_company_rank": round(float(avg_company_rank), 2) if avg_company_rank is not None else None,
            "target_question_count": target_question_count,
            "covered_question_count": covered_question_count,
            "question_coverage_rate": round(question_coverage_rate, 4),
            "keyword_count": keyword_count,
            "covered_keyword_count": covered_keyword_count,
            "keyword_coverage_rate": round(keyword_coverage_rate, 4),
            "provider_count": provider_count,
            "manual_correction_count": manual_correction_count,
            "manual_correction_rate": round(manual_correction_count / denominator, 4),
        },
        "top_competitors": [
            {"name": row.entity_name, "mentions": int(row.mentions or 0)} for row in top_competitors
        ],
        "provider_breakdown": [
            {
                "provider_id": row.provider_id,
                "provider_name": row.name or "unknown",
                "provider_type": row.provider_type or "unknown",
                "answer_count": int(row.answer_count or 0),
            }
            for row in provider_breakdown
        ],
        "top_sources": [
            {
                "domain": row.source_domain,
                "url": row.source_url,
                "mentions": int(row.mentions or 0),
                "is_owned": bool(row.is_owned),
                "is_placed": bool(row.is_placed),
                "ai_readiness_score": int(row.ai_readiness_score or 0),
            }
            for row in top_sources
        ],
        "source_gaps": [
            {
                "domain": row.source_domain,
                "url": row.source_url,
                "mentions": int(row.mentions or 0),
                "reason": "高频出现但尚未标记为自有或已投放信源",
            }
            for row in top_sources
            if not row.is_owned and not row.is_placed
        ],
        "question_gaps": [
            {"target_question_id": row.id, "question_text": row.question_text} for row in question_gaps
        ],
        "keyword_gaps": [
            {"keyword_id": row.id, "keyword": row.keyword} for row in keyword_gaps
        ],
        "coverage": {
            "target_question_count": target_question_count,
            "covered_question_count": covered_question_count,
            "question_coverage_rate": round(question_coverage_rate, 4),
            "keyword_count": keyword_count,
            "covered_keyword_count": covered_keyword_count,
            "keyword_coverage_rate": round(keyword_coverage_rate, 4),
            "keyword_prompt_variant_target": keyword_prompt_coverage["target_variant_count"],
            "keyword_full_prompt_coverage_count": keyword_prompt_coverage["full_coverage_count"],
            "keyword_prompt_coverage_rate": keyword_prompt_coverage["coverage_rate"],
            "avg_prompt_variants_per_keyword": keyword_prompt_coverage["avg_prompt_variants_per_keyword"],
            "provider_count": provider_count,
            "sample_size": total_answers,
            "coverage_status": (
                "ready"
                if total_answers >= 20 and question_coverage_rate >= 0.8 and keyword_coverage_rate >= 0.8
                else "partial"
                if total_answers >= 10
                else "thin"
            ),
        },
        "evidence_quality": {
            "sample_size": total_answers,
            **evidence_source_mix,
            "provider_count": provider_count,
            "sample_confidence_score": sample_confidence_score,
            "risk_level": "high" if total_answers < 5 or provider_count < 2 else "medium" if total_answers < 10 else "low",
            "notes": [
                "样本量越大、模型覆盖越多，成熟度判断越可靠。",
                "Mock 渠道可验证系统闭环，但正式报告应使用真实大模型采集结果。",
                "网页端观测样本适合校验真实产品页面表现，应保留截图或录屏证据。",
            ],
        },
        "evidence_samples": evidence_samples,
        "keyword_prompt_coverage": keyword_prompt_coverage,
        "brand_visibility_matrix": brand_visibility_matrix,
        "delivery_readiness": delivery_readiness,
        "report_template_snapshot": template_snapshot,
        "template_score_alignment": template_score_alignment,
        "recommendations": recommendations,
        "next_content_topics": [
            f"{project.target_industry or company.industry if company else '行业'}服务商怎么选？",
            f"{company.name if company else '企业'}在{project.target_industry or '目标行业'}中的解决方案能力说明",
            "企业 GEO 优化常见问题 FAQ",
        ],
    }

    report = MaturityReport(
        project_id=project.id,
        title=payload.title or f"{project.name} GEO 成熟度诊断报告",
        report_period=payload.report_period,
        total_score=total_score,
        maturity_level=_level(total_score),
        summary=(
            f"本次共分析 {total_answers} 条 AI 答案样本，企业提及率 {mention_rate:.0%}，"
            f"推荐率 {recommendation_rate:.0%}。"
        ),
        report_json=report_json,
        status="generated",
        generated_at=datetime.now(UTC),
    )
    db.add(report)
    db.flush()

    for dimension, score, max_score, explanation, metric_keys in score_items_data:
        db.add(
            MaturityScoreItem(
                report_id=report.id,
                dimension=dimension,
                score=score,
                max_score=max_score,
                explanation=explanation,
                evidence_json={
                    "project_id": project.id,
                    "metric_keys": metric_keys,
                    "supporting_result_ids": supporting_result_ids[:8],
                    "sample_count": total_answers,
                    "provider_count": provider_count,
                },
            )
        )
    db.commit()
    db.refresh(report)
    return report


def generate_task_competitive_report(
    db: Session,
    project: Project,
    task: CrawlTask,
    payload: MaturityReportCreate,
) -> MaturityReport:
    """Generate an auditable report from one crawl task only.

    This is intentionally separate from the cumulative maturity report so a
    weekly 100-call evaluation cannot silently include historical samples.
    """
    company = db.get(Company, project.company_id)
    result_filter = CrawlResult.task_id == task.id
    total_answers = int(
        db.scalar(select(func.count()).select_from(CrawlResult).where(result_filter)) or 0
    )
    expected_answers = (
        (len(task.target_question_ids) + len(task.keyword_ids) * KEYWORD_PROMPT_VARIANT_COUNT)
        * len(task.provider_ids)
        * max(1, task.sample_runs_per_prompt or 1)
    )
    company_mentions = int(
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(result_filter, AnswerAnalysis.company_mentioned.is_(True))
        )
        or 0
    )
    company_recommendations = int(
        db.scalar(
            select(func.count())
            .select_from(AnswerAnalysis)
            .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
            .where(result_filter, AnswerAnalysis.company_recommended.is_(True))
        )
        or 0
    )
    avg_company_rank = db.scalar(
        select(func.avg(AnswerAnalysis.company_rank))
        .join(CrawlResult, CrawlResult.id == AnswerAnalysis.crawl_result_id)
        .where(result_filter, AnswerAnalysis.company_rank.is_not(None))
    )
    competitor_rows = db.execute(
        select(
            MentionedEntity.entity_name,
            func.count(func.distinct(MentionedEntity.crawl_result_id)).label("answer_mentions"),
            func.sum(MentionedEntity.mention_count).label("mention_count"),
            func.count(MentionedEntity.recommendation_rank).label("recommendation_count"),
            func.avg(MentionedEntity.recommendation_rank).label("avg_rank"),
        )
        .join(CrawlResult, CrawlResult.id == MentionedEntity.crawl_result_id)
        .where(result_filter, MentionedEntity.is_competitor.is_(True))
        .group_by(MentionedEntity.entity_name)
        .order_by(func.count(func.distinct(MentionedEntity.crawl_result_id)).desc())
    ).all()
    provider_rows = db.execute(
        select(
            LLMProvider.id,
            LLMProvider.name,
            LLMProvider.provider_type,
            func.count(CrawlResult.id).label("answer_count"),
        )
        .join(CrawlResult, CrawlResult.provider_id == LLMProvider.id)
        .where(result_filter)
        .group_by(LLMProvider.id, LLMProvider.name, LLMProvider.provider_type)
    ).all()
    task_providers = [db.get(LLMProvider, provider_id) for provider_id in task.provider_ids]
    live_search_provider_ids = {
        provider.id
        for provider in task_providers
        if provider is not None
        and (
            provider.provider_type in {"kimi_web_search", "browser_observation"}
            or (
                provider.provider_type == "qwen_compatible"
                and bool((provider.cost_rule or {}).get("enable_search"))
            )
        )
    }
    live_search_answer_count = sum(
        int(row.answer_count or 0) for row in provider_rows if row.id in live_search_provider_ids
    )
    source_count = int(
        db.scalar(
            select(func.count())
            .select_from(CitationSource)
            .join(CrawlResult, CrawlResult.id == CitationSource.crawl_result_id)
            .where(result_filter)
        )
        or 0
    )
    browser_observation_count = int(
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .join(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
            .where(result_filter, LLMProvider.provider_type == "browser_observation")
        )
        or 0
    )
    mock_count = int(
        db.scalar(
            select(func.count())
            .select_from(CrawlResult)
            .join(LLMProvider, LLMProvider.id == CrawlResult.provider_id)
            .where(result_filter, LLMProvider.provider_type == "mock")
        )
        or 0
    )

    denominator = total_answers or 1
    mention_rate = company_mentions / denominator
    recommendation_rate = company_recommendations / denominator
    completion_rate = min(1.0, total_answers / (expected_answers or 1))
    avg_rank_value = float(avg_company_rank) if avg_company_rank is not None else None
    rank_quality = max(0.0, 1 - ((avg_rank_value - 1) / 9)) if avg_rank_value is not None else 0.0
    competitor_recommendations = sum(int(row.recommendation_count or 0) for row in competitor_rows)
    competitive_share = company_recommendations / (
        company_recommendations + competitor_recommendations or 1
    )
    visibility_score = _score_rate(mention_rate, 30)
    recommendation_score = _score_rate(recommendation_rate, 25)
    rank_coverage = min(1.0, company_recommendations / 10)
    rank_score = _score_rate(rank_quality * rank_coverage, 15)
    competitive_score = _score_rate(competitive_share, 15)
    verified_source_count = source_count if live_search_answer_count > 0 else 0
    evidence_score = _score_rate(min(1.0, verified_source_count / denominator), 10)
    completeness_score = _score_rate(completion_rate, 5)
    score_items_data = [
        ("品牌提及", visibility_score, 30, f"本任务 {company_mentions}/{total_answers} 条回答提及企业。"),
        ("品牌推荐", recommendation_score, 25, f"本任务 {company_recommendations}/{total_answers} 条回答推荐企业。"),
        ("推荐排名", rank_score, 15, f"企业平均推荐排名：{avg_rank_value if avg_rank_value is not None else '无排名样本'}；按 {company_recommendations} 条推荐样本折算。"),
        ("竞品对比", competitive_score, 15, f"企业推荐 {company_recommendations} 次，竞品推荐位 {competitor_recommendations} 次。"),
        ("信源证据", evidence_score, 10, f"有效联网信源 {verified_source_count} 条；普通 API 回答中的 {source_count - verified_source_count} 条 URL 仅作待核验线索。"),
        ("样本完整性", completeness_score, 5, f"完成 {total_answers}/{expected_answers} 次计划调用。"),
    ]
    total_score = sum(item[1] for item in score_items_data)
    report = MaturityReport(
        project_id=project.id,
        title=payload.title or f"{project.name} 每周模型搜索与竞品分析报告",
        report_period=payload.report_period,
        total_score=total_score,
        maturity_level=_level(total_score),
        summary=(
            f"报告严格限定采集任务 #{task.id}，共 {total_answers}/{expected_answers} 条结果；"
            f"品牌提及率 {mention_rate:.1%}，推荐率 {recommendation_rate:.1%}。"
        ),
        report_json={
            "report_type": "task_scoped_weekly_competitive_analysis",
            "scope": {
                "crawl_task_id": task.id,
                "expected_answer_count": expected_answers,
                "actual_answer_count": total_answers,
                "historical_results_excluded": True,
                "provider_ids": task.provider_ids,
                "sample_runs_per_prompt": task.sample_runs_per_prompt,
            },
            "evidence_source_mix": {
                "api_sample_count": total_answers - browser_observation_count - mock_count,
                "browser_observation_count": browser_observation_count,
                "mock_sample_count": mock_count,
                "citation_source_count": source_count,
                "verified_citation_source_count": verified_source_count,
                "unverified_claimed_url_count": source_count - verified_source_count,
                "live_search_answer_count": live_search_answer_count,
                "web_search_claim_allowed": live_search_answer_count > 0,
            },
            "metrics": {
                "total_answers": total_answers,
                "company_mentions": company_mentions,
                "company_recommendations": company_recommendations,
                "mention_rate": round(mention_rate, 4),
                "recommendation_rate": round(recommendation_rate, 4),
                "avg_company_rank": round(avg_rank_value, 2) if avg_rank_value is not None else None,
                "completion_rate": round(completion_rate, 4),
                "competitive_recommendation_share": round(competitive_share, 4),
            },
            "providers": [
                {"id": row.id, "name": row.name, "provider_type": row.provider_type, "answer_count": int(row.answer_count)}
                for row in provider_rows
            ],
            "competitors": [
                {
                    "name": row.entity_name,
                    "answer_mentions": int(row.answer_mentions or 0),
                    "mention_count": int(row.mention_count or 0),
                    "recommendation_count": int(row.recommendation_count or 0),
                    "avg_rank": round(float(row.avg_rank), 2) if row.avg_rank is not None else None,
                }
                for row in competitor_rows
            ],
            "company": company.name if company else None,
        },
        status="generated",
        generated_at=datetime.now(UTC),
    )
    db.add(report)
    db.flush()
    for dimension, score, max_score, explanation in score_items_data:
        db.add(
            MaturityScoreItem(
                report_id=report.id,
                dimension=dimension,
                score=score,
                max_score=max_score,
                explanation=explanation,
                evidence_json={"crawl_task_id": task.id},
            )
        )
    db.flush()
    return report


def compare_maturity_reports(
    db: Session, project: Project, base_report: MaturityReport, target_report: MaturityReport
) -> dict:
    base_metrics = (base_report.report_json or {}).get("metrics", {})
    target_metrics = (target_report.report_json or {}).get("metrics", {})
    metric_keys = sorted(set(base_metrics.keys()) | set(target_metrics.keys()))
    metric_deltas = {}
    for key in metric_keys:
        base_value = base_metrics.get(key, 0)
        target_value = target_metrics.get(key, 0)
        if isinstance(base_value, (int, float)) and isinstance(target_value, (int, float)):
            metric_deltas[key] = {
                "base": base_value,
                "target": target_value,
                "delta": round(target_value - base_value, 4),
            }

    base_items = {
        item.dimension: item
        for item in db.scalars(
            select(MaturityScoreItem)
            .where(MaturityScoreItem.report_id == base_report.id)
            .order_by(MaturityScoreItem.id.asc())
        )
    }
    target_items = {
        item.dimension: item
        for item in db.scalars(
            select(MaturityScoreItem)
            .where(MaturityScoreItem.report_id == target_report.id)
            .order_by(MaturityScoreItem.id.asc())
        )
    }
    dimension_deltas = []
    for dimension in sorted(set(base_items) | set(target_items)):
        base_item = base_items.get(dimension)
        target_item = target_items.get(dimension)
        base_score = base_item.score if base_item else 0
        target_score = target_item.score if target_item else 0
        dimension_deltas.append(
            {
                "dimension": dimension,
                "base_score": base_score,
                "target_score": target_score,
                "delta": target_score - base_score,
                "max_score": target_item.max_score if target_item else base_item.max_score if base_item else 100,
            }
        )

    total_score_delta = target_report.total_score - base_report.total_score
    summary = (
        f"{project.name} 本期 GEO 成熟度总分较基准报告"
        f"{'提升' if total_score_delta >= 0 else '下降'} {abs(total_score_delta)} 分，"
        f"等级由 {base_report.maturity_level} 变为 {target_report.maturity_level}。"
    )
    recommendations = []
    if total_score_delta < 0:
        recommendations.append("成熟度总分下降，建议优先复查近期 AI 答案中竞品提及和信源变化。")
    elif total_score_delta == 0:
        recommendations.append("成熟度总分持平，建议扩大样本量并针对高价值问题补充直答型内容。")
    else:
        recommendations.append("成熟度总分提升，建议延续有效选题和投放渠道，并监测是否稳定进入推荐。")

    mention_delta = metric_deltas.get("mention_rate", {}).get("delta", 0)
    recommendation_delta = metric_deltas.get("recommendation_rate", {}).get("delta", 0)
    if mention_delta <= 0:
        recommendations.append("企业提及率未明显提升，建议补齐官网 FAQ、案例页和第三方报道信源。")
    if recommendation_delta <= 0:
        recommendations.append("企业推荐率未明显提升，建议强化对比理由、适用场景和案例证据。")
    if metric_deltas.get("competitor_pressure", {}).get("delta", 0) > 0:
        recommendations.append("竞品压力上升，建议围绕竞品高频问题做反向内容布局。")

    return {
        "project_id": project.id,
        "base_report": base_report,
        "target_report": target_report,
        "total_score_delta": total_score_delta,
        "maturity_level_changed": base_report.maturity_level != target_report.maturity_level,
        "metric_deltas": metric_deltas,
        "dimension_deltas": dimension_deltas,
        "summary": summary,
        "recommendations": recommendations,
    }


def render_report_markdown(report: MaturityReport, items: list[MaturityScoreItem]) -> str:
    data = report.report_json or {}
    competitive_document = data.get("competitive_analysis_document") or {}
    if competitive_document.get("markdown"):
        return str(competitive_document["markdown"])
    metrics = data.get("metrics", {})
    recommendations = data.get("recommendations", [])
    topics = data.get("next_content_topics", [])
    competitors = data.get("top_competitors", [])
    provider_breakdown = data.get("provider_breakdown", [])
    top_sources = data.get("top_sources", [])
    source_gaps = data.get("source_gaps", [])
    question_gaps = data.get("question_gaps", [])
    keyword_gaps = data.get("keyword_gaps", [])
    coverage = data.get("coverage", {})
    keyword_prompt_coverage = data.get("keyword_prompt_coverage", {})
    evidence_quality = data.get("evidence_quality", {})
    evidence_samples = data.get("evidence_samples", [])
    brand_matrix = data.get("brand_visibility_matrix", {})
    brand_summary = brand_matrix.get("summary", [])
    brand_by_provider = brand_matrix.get("by_provider", [])
    delivery_readiness = data.get("delivery_readiness", {})
    delivery_checks = delivery_readiness.get("checks", [])
    template_snapshot = data.get("report_template_snapshot", {})
    lines = [
        f"# {report.title}",
        "",
        f"总分：{report.total_score}",
        f"成熟度等级：{report.maturity_level}",
        f"报告模板：{template_snapshot.get('name', '默认模板')} v{template_snapshot.get('version', 1)}",
        "",
        "## 摘要",
        "",
        report.summary or "",
        "",
        "## 核心指标",
        "",
        f"- AI 答案样本数：{metrics.get('total_answers', 0)}",
        f"- 企业提及数：{metrics.get('company_mentions', 0)}",
        f"- 企业推荐数：{metrics.get('company_recommendations', 0)}",
        f"- 企业提及率：{metrics.get('mention_rate', 0):.0%}",
        f"- 企业推荐率：{metrics.get('recommendation_rate', 0):.0%}",
        f"- 平均推荐位：{metrics.get('avg_company_rank') or '暂无'}",
        f"- 正向答案率：{metrics.get('positive_rate', 0):.0%}",
        f"- 自有信源占比：{metrics.get('owned_source_rate', 0):.0%}",
        f"- 已投放信源占比：{metrics.get('placed_source_rate', 0):.0%}",
        f"- 问题覆盖率：{metrics.get('question_coverage_rate', 0):.0%}",
        f"- 关键词覆盖率：{metrics.get('keyword_coverage_rate', 0):.0%}",
        "",
        "## 覆盖摘要",
        "",
        f"- 覆盖状态：{coverage.get('coverage_status', 'unknown')}",
        f"- 目标问题：{coverage.get('covered_question_count', 0)}/{coverage.get('target_question_count', 0)}",
        f"- 关键词：{coverage.get('covered_keyword_count', 0)}/{coverage.get('keyword_count', 0)}",
        f"- 关键词语境完整覆盖：{coverage.get('keyword_full_prompt_coverage_count', 0)}/{coverage.get('keyword_count', 0)}",
        f"- 平均每关键词问题变体：{coverage.get('avg_prompt_variants_per_keyword', 0)}",
        f"- 模型渠道：{coverage.get('provider_count', 0)}",
        f"- 样本量：{coverage.get('sample_size', 0)}",
        "",
        "关键词语境明细：",
    ]
    for item in (keyword_prompt_coverage.get("items") or [])[:10]:
        lines.append(
            f"- {item.get('keyword')}：{item.get('prompt_variant_count', 0)}/"
            f"{item.get('target_variant_count', 3)} 个变体｜{item.get('coverage_status')}｜"
            f"模型 {item.get('provider_count', 0)}｜结果 {item.get('result_count', 0)}"
        )
    lines.extend([
        "",
        "## 样本可信度",
        "",
        f"- 样本可信度分：{evidence_quality.get('sample_confidence_score', 0)}/100",
        f"- 风险等级：{evidence_quality.get('risk_level', 'unknown')}",
        f"- 覆盖模型数：{evidence_quality.get('provider_count', 0)}",
        f"- 真实 API 样本数：{evidence_quality.get('real_api_sample_count', 0)}",
        f"- 真实 Provider 数：{evidence_quality.get('real_provider_count', 0)}",
        f"- 真实样本占比：{evidence_quality.get('real_sample_rate', 0):.0%}",
        f"- Mock 样本数：{evidence_quality.get('mock_sample_count', 0)}",
        f"- API 样本数：{evidence_quality.get('api_sample_count', 0)}",
        f"- 网页端观测样本数：{evidence_quality.get('browser_observation_count', 0)}",
        f"- 网页端覆盖平台数：{evidence_quality.get('browser_observation_platform_count', 0)}",
        f"- 网页端覆盖平台：{'、'.join(evidence_quality.get('browser_observation_platforms') or []) or '暂无'}",
        f"- 截图/录屏证据数：{evidence_quality.get('screenshot_evidence_count', 0)}",
        f"- 人工校正样本数：{evidence_quality.get('manual_correction_count', 0)}",
        f"- 人工校正占比：{evidence_quality.get('manual_correction_rate', 0):.0%}",
        "",
        "## 交付就绪度",
        "",
        f"- 状态：{delivery_readiness.get('status', 'unknown')}",
        f"- 得分：{delivery_readiness.get('score', 0)}/100",
        f"- 阻塞项：{delivery_readiness.get('blocker_count', 0)}",
        f"- 结论：{delivery_readiness.get('summary', '暂无')}",
        "",
        "检查项：",
    ])
    for item in delivery_checks:
        lines.append(
            f"- {'通过' if item.get('ok') else '待补'}｜{item.get('label')}："
            f"{item.get('current')}/{item.get('required')}｜{item.get('fix')}"
        )
    lines.extend([
        "## 评分明细",
        "",
    ])
    for item in items:
        lines.append(f"- {item.dimension}：{item.score}/{item.max_score}。{item.explanation or ''}")
    lines.extend(["", "## 品牌推荐矩阵", ""])
    lines.append(f"- 当前领先品牌：{brand_matrix.get('leader_name') or '暂无'}")
    lines.append(f"- 企业榜单位置：{brand_matrix.get('company_position') or '暂无'}")
    if brand_summary:
        lines.append("")
        lines.append("品牌榜单：")
        for item in brand_summary[:8]:
            lines.append(
                f"- {item.get('name')}｜{item.get('brand_type')}｜提及 {item.get('mention_count', 0)} 次｜"
                f"推荐 {item.get('recommendation_count', 0)} 次｜覆盖模型 {item.get('provider_count', 0)}｜"
                f"平均推荐位 {item.get('avg_rank') or '暂无'}"
            )
    if brand_by_provider:
        lines.append("")
        lines.append("模型分布：")
        for item in brand_by_provider[:8]:
            top_entity_names = "、".join(entity.get("name", "") for entity in item.get("top_entities", [])[:3])
            lines.append(
                f"- {item.get('provider_name')}｜样本 {item.get('answer_count', 0)}｜"
                f"企业提及率 {item.get('company_mention_rate', 0):.0%}｜"
                f"企业推荐率 {item.get('company_recommendation_rate', 0):.0%}｜"
                f"平均推荐位 {item.get('company_avg_rank') or '暂无'}"
                + (f"｜高频品牌：{top_entity_names}" if top_entity_names else "")
            )
    lines.extend(["", "## 竞品表现", ""])
    if competitors:
        for item in competitors:
            lines.append(f"- {item.get('name')}：提及 {item.get('mentions')} 次")
    else:
        lines.append("- 暂无竞品提及数据")
    lines.extend(["", "## 模型覆盖", ""])
    if provider_breakdown:
        for item in provider_breakdown:
            lines.append(f"- {item.get('provider_name')}：{item.get('answer_count')} 条答案")
    else:
        lines.append("- 暂无模型覆盖数据")
    lines.extend(["", "## 高频信源", ""])
    if top_sources:
        for item in top_sources:
            flags = []
            if item.get("is_owned"):
                flags.append("自有")
            if item.get("is_placed"):
                flags.append("已投放")
            lines.append(
                f"- {item.get('domain') or item.get('url') or '未知信源'}：出现 {item.get('mentions')} 次，"
                f"AI 适配分 {item.get('ai_readiness_score')}，{'/'.join(flags) if flags else '待建设'}"
            )
    else:
        lines.append("- 暂无信源数据")
    lines.extend(["", "## 信源缺口", ""])
    if source_gaps:
        for item in source_gaps:
            lines.append(f"- {item.get('domain') or item.get('url')}：{item.get('reason')}")
    else:
        lines.append("- 暂无明显信源缺口")
    lines.extend(["", "## 采集缺口", ""])
    if question_gaps:
        for item in question_gaps:
            lines.append(f"- {item.get('question_text')}")
    else:
        lines.append("- 目标问题已被当前样本覆盖")
    if keyword_gaps:
        lines.extend(["", "关键词缺口："])
        for item in keyword_gaps:
            lines.append(f"- {item.get('keyword')}")
    else:
        lines.append("- 关键词已被当前样本覆盖")
    lines.extend(["", "## 优化建议", ""])
    for item in recommendations:
        lines.append(f"- {item}")
    lines.extend(["", "## 推荐选题", ""])
    for item in topics:
        lines.append(f"- {item}")
    lines.extend(["", "## 证据样本附录", ""])
    if evidence_samples:
        for item in evidence_samples[:12]:
            flags = []
            if item.get("company_mentioned"):
                flags.append("提及企业")
            if item.get("company_recommended"):
                flags.append("推荐企业")
            if item.get("manual_corrected"):
                flags.append("人工校正")
            source_text = "、".join(
                source.get("domain") or source.get("url") or "未知信源"
                for source in item.get("top_sources", [])[:3]
            )
            lines.append(
                f"- 样本 #{item.get('crawl_result_id')}｜{item.get('provider_name')}｜"
                f"{'，'.join(flags) if flags else '未提及'}｜置信度 {item.get('confidence', 0)}｜"
                f"问题：{item.get('prompt_text')}｜摘要：{item.get('answer_summary') or '暂无'}"
                + (f"｜信源：{source_text}" if source_text else "")
            )
    else:
        lines.append("- 暂无可追溯答案样本")
    lines.append("")
    return "\n".join(lines)


def render_report_pdf(report: MaturityReport, items: list[MaturityScoreItem]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font_name = "Helvetica"
    for font_path in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]:
        try:
            pdfmetrics.registerFont(TTFont("GeoCJK", font_path))
            font_name = "GeoCJK"
            break
        except Exception:
            continue

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "GeoTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=20,
        leading=26,
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "GeoHeading",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=14,
        leading=18,
        spaceBefore=12,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "GeoBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=10,
        leading=16,
        spaceAfter=6,
    )

    data = report.report_json or {}
    metrics = data.get("metrics", {})
    recommendations = data.get("recommendations", [])
    topics = data.get("next_content_topics", [])
    provider_breakdown = data.get("provider_breakdown", [])
    top_sources = data.get("top_sources", [])
    source_gaps = data.get("source_gaps", [])
    question_gaps = data.get("question_gaps", [])
    keyword_gaps = data.get("keyword_gaps", [])
    coverage = data.get("coverage", {})
    evidence_quality = data.get("evidence_quality", {})
    evidence_samples = data.get("evidence_samples", [])
    brand_matrix = data.get("brand_visibility_matrix", {})
    brand_summary = brand_matrix.get("summary", [])
    brand_by_provider = brand_matrix.get("by_provider", [])
    delivery_readiness = data.get("delivery_readiness", {})
    delivery_checks = delivery_readiness.get("checks", [])
    template_snapshot = data.get("report_template_snapshot", {})

    story = [
        Paragraph(report.title, title_style),
        Paragraph(f"总分：{report.total_score}　成熟度等级：{report.maturity_level}", body_style),
        Paragraph(
            f"报告模板：{template_snapshot.get('name', '默认模板')} v{template_snapshot.get('version', 1)}",
            body_style,
        ),
        Spacer(1, 6),
        Paragraph("摘要", heading_style),
        Paragraph(report.summary or "", body_style),
        Paragraph("核心指标", heading_style),
        Paragraph(
            f"AI 答案样本数：{metrics.get('total_answers', 0)}<br/>"
            f"企业提及数：{metrics.get('company_mentions', 0)}<br/>"
            f"企业推荐数：{metrics.get('company_recommendations', 0)}<br/>"
            f"企业提及率：{metrics.get('mention_rate', 0):.0%}<br/>"
            f"企业推荐率：{metrics.get('recommendation_rate', 0):.0%}<br/>"
            f"平均推荐位：{metrics.get('avg_company_rank') or '暂无'}<br/>"
            f"自有信源占比：{metrics.get('owned_source_rate', 0):.0%}<br/>"
            f"问题覆盖率：{metrics.get('question_coverage_rate', 0):.0%}<br/>"
            f"关键词覆盖率：{metrics.get('keyword_coverage_rate', 0):.0%}",
            body_style,
        ),
        Paragraph("覆盖摘要", heading_style),
        Paragraph(
            f"覆盖状态：{coverage.get('coverage_status', 'unknown')}<br/>"
            f"目标问题：{coverage.get('covered_question_count', 0)}/{coverage.get('target_question_count', 0)}<br/>"
            f"关键词：{coverage.get('covered_keyword_count', 0)}/{coverage.get('keyword_count', 0)}<br/>"
            f"模型渠道：{coverage.get('provider_count', 0)}<br/>"
            f"样本量：{coverage.get('sample_size', 0)}",
            body_style,
        ),
        Paragraph("样本可信度", heading_style),
        Paragraph(
            f"样本可信度分：{evidence_quality.get('sample_confidence_score', 0)}/100<br/>"
            f"风险等级：{evidence_quality.get('risk_level', 'unknown')}<br/>"
            f"覆盖模型数：{evidence_quality.get('provider_count', 0)}<br/>"
            f"真实 API 样本数：{evidence_quality.get('real_api_sample_count', 0)}<br/>"
            f"真实 Provider 数：{evidence_quality.get('real_provider_count', 0)}<br/>"
            f"真实样本占比：{evidence_quality.get('real_sample_rate', 0):.0%}<br/>"
            f"Mock 样本数：{evidence_quality.get('mock_sample_count', 0)}<br/>"
            f"API 样本数：{evidence_quality.get('api_sample_count', 0)}<br/>"
            f"网页端观测样本数：{evidence_quality.get('browser_observation_count', 0)}<br/>"
            f"网页端覆盖平台数：{evidence_quality.get('browser_observation_platform_count', 0)}<br/>"
            f"网页端覆盖平台：{'、'.join(evidence_quality.get('browser_observation_platforms') or []) or '暂无'}<br/>"
            f"截图/录屏证据数：{evidence_quality.get('screenshot_evidence_count', 0)}<br/>"
            f"人工校正样本数：{evidence_quality.get('manual_correction_count', 0)}<br/>"
            f"人工校正占比：{evidence_quality.get('manual_correction_rate', 0):.0%}",
            body_style,
        ),
        Paragraph("交付就绪度", heading_style),
        Paragraph(
            f"状态：{delivery_readiness.get('status', 'unknown')}<br/>"
            f"得分：{delivery_readiness.get('score', 0)}/100<br/>"
            f"阻塞项：{delivery_readiness.get('blocker_count', 0)}<br/>"
            f"结论：{delivery_readiness.get('summary', '暂无')}",
            body_style,
        ),
    ]
    for item in delivery_checks:
        story.append(
            Paragraph(
                f"{'通过' if item.get('ok') else '待补'}｜{item.get('label')}："
                f"{item.get('current')}/{item.get('required')}｜{item.get('fix')}",
                body_style,
            )
        )
    story.extend([
        Paragraph("评分明细", heading_style),
    ])
    for item in items:
        story.append(
            Paragraph(
                f"{item.dimension}：{item.score}/{item.max_score}。{item.explanation or ''}",
                body_style,
            )
        )
    story.append(Paragraph("品牌推荐矩阵", heading_style))
    story.append(
        Paragraph(
            f"当前领先品牌：{brand_matrix.get('leader_name') or '暂无'}<br/>"
            f"企业榜单位置：{brand_matrix.get('company_position') or '暂无'}",
            body_style,
        )
    )
    if brand_summary:
        for item in brand_summary[:8]:
            story.append(
                Paragraph(
                    f"{item.get('name')}｜{item.get('brand_type')}｜提及 {item.get('mention_count', 0)} 次｜"
                    f"推荐 {item.get('recommendation_count', 0)} 次｜覆盖模型 {item.get('provider_count', 0)}｜"
                    f"平均推荐位 {item.get('avg_rank') or '暂无'}",
                    body_style,
                )
            )
    if brand_by_provider:
        story.append(Paragraph("模型分布", heading_style))
        for item in brand_by_provider[:6]:
            top_entity_names = "、".join(entity.get("name", "") for entity in item.get("top_entities", [])[:3])
            story.append(
                Paragraph(
                    f"{item.get('provider_name')}｜样本 {item.get('answer_count', 0)}｜"
                    f"企业提及率 {item.get('company_mention_rate', 0):.0%}｜"
                    f"企业推荐率 {item.get('company_recommendation_rate', 0):.0%}｜"
                    f"平均推荐位 {item.get('company_avg_rank') or '暂无'}"
                    + (f"｜高频品牌：{top_entity_names}" if top_entity_names else ""),
                    body_style,
                )
            )
    story.append(Paragraph("模型覆盖", heading_style))
    if provider_breakdown:
        for item in provider_breakdown:
            story.append(Paragraph(f"{item.get('provider_name')}：{item.get('answer_count')} 条答案", body_style))
    else:
        story.append(Paragraph("暂无模型覆盖数据", body_style))
    story.append(Paragraph("高频信源与缺口", heading_style))
    if top_sources:
        for item in top_sources[:8]:
            story.append(
                Paragraph(
                    f"{item.get('domain') or item.get('url') or '未知信源'}：出现 {item.get('mentions')} 次，"
                    f"AI 适配分 {item.get('ai_readiness_score')}",
                    body_style,
                )
            )
    else:
        story.append(Paragraph("暂无信源数据", body_style))
    if source_gaps:
        for item in source_gaps[:5]:
            story.append(Paragraph(f"缺口：{item.get('domain') or item.get('url')}，{item.get('reason')}", body_style))
    if question_gaps or keyword_gaps:
        story.append(Paragraph("采集缺口", heading_style))
    if question_gaps:
        for item in question_gaps[:5]:
            story.append(Paragraph(f"未覆盖问题：{item.get('question_text')}", body_style))
    if keyword_gaps:
        for item in keyword_gaps[:5]:
            story.append(Paragraph(f"未覆盖关键词：{item.get('keyword')}", body_style))
    story.append(Paragraph("优化建议", heading_style))
    for item in recommendations:
        story.append(Paragraph(f"• {item}", body_style))
    story.append(Paragraph("推荐选题", heading_style))
    for item in topics:
        story.append(Paragraph(f"• {item}", body_style))
    story.append(Paragraph("证据样本附录", heading_style))
    if evidence_samples:
        for item in evidence_samples[:8]:
            flags = []
            if item.get("company_mentioned"):
                flags.append("提及企业")
            if item.get("company_recommended"):
                flags.append("推荐企业")
            if item.get("manual_corrected"):
                flags.append("人工校正")
            story.append(
                Paragraph(
                    f"样本 #{item.get('crawl_result_id')}｜{item.get('provider_name')}｜"
                    f"{'，'.join(flags) if flags else '未提及'}｜置信度 {item.get('confidence', 0)}<br/>"
                    f"问题：{item.get('prompt_text')}<br/>"
                    f"摘要：{item.get('answer_summary') or '暂无'}",
                    body_style,
                )
            )
    else:
        story.append(Paragraph("暂无可追溯答案样本", body_style))

    doc.build(story)
    return buffer.getvalue()
