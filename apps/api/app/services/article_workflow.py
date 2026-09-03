from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ArticleDraft,
    ArticleReview,
    Company,
    ContentAsset,
    ContentAssetReview,
    Keyword,
    MaturityReport,
    Project,
    ReviewRule,
    TargetQuestion,
)
from app.schemas.content import ArticleDraftGenerate
from app.services.review_rules import get_active_review_rules, review_rule_snapshot


def _match_text_items(text: str, items: list[str], *, limit: int = 5) -> list[str]:
    return [item for item in items if item and item in text][:limit]


def _source_gap_label(item: dict[str, Any]) -> str | None:
    value = item.get("domain") or item.get("url") or item.get("source_name")
    return str(value) if value else None


def _topic_focus(topic: str) -> dict[str, str]:
    normalized = topic.lower()
    if any(marker in topic for marker in ["Token", "token", "成本", "分摊", "费用", "黑洞"]):
        return {
            "pain": "Token 消耗分散在不同模型、部门和项目里，企业很难判断预算花在哪里、由谁产生、是否带来了业务价值。",
            "capability": "统一接入、Token 计量、预算配额、成本归因、异常告警和账单分摊",
            "scenario": "多部门共用大模型、研发和业务团队并行接入 AI 服务、财务需要按部门或项目核算 AI 成本",
            "evidence": "调用明细、Token 账单、部门配额、项目成本报表和异常消耗记录",
        }
    if any(marker in topic for marker in ["密钥", "Key", "key", "滥用", "权限"]):
        return {
            "pain": "API Key 分散在个人电脑、脚本、测试环境和不同系统中，容易出现泄露、越权调用和离职人员权限残留。",
            "capability": "API 密钥托管、权限隔离、调用审计、密钥轮换、黑白名单和用量限制",
            "scenario": "企业统一管理各部门的大模型 API Key，并限制不同团队、项目和应用的调用边界",
            "evidence": "密钥授权记录、调用日志、审计报表、权限变更记录和异常访问告警",
        }
    if any(marker in normalized for marker in ["gateway", "网关", "maas", "接入", "多模型", "api 治理", "llm"]):
        return {
            "pain": "企业同时接入多个大模型后，模型协议、鉴权方式、调用稳定性、成本口径和审计要求往往不一致。",
            "capability": "多模型统一接入、请求路由、失败重试、限流熔断、统一鉴权和可观测性",
            "scenario": "企业希望通过一层 API 网关稳定接入 DeepSeek、豆包、Kimi、GLM 等不同模型服务",
            "evidence": "模型调用成功率、延迟统计、错误日志、路由策略、降级记录和服务可用性报表",
        }
    if any(marker in topic for marker in ["合规", "审计", "政企", "可观测"]):
        return {
            "pain": "政企客户使用大模型时，需要证明调用可追溯、数据可管控、权限可审计、风险可处置。",
            "capability": "调用审计、内容留痕、权限分级、合规报表、敏感数据管控和风险告警",
            "scenario": "政企单位、集团企业或强监管行业在内网或专有云中统一治理 AI 调用",
            "evidence": "审计日志、合规策略、风险事件、权限审批记录和监管检查材料",
        }
    return {
        "pain": "企业使用大模型进入规模化阶段后，容易出现接入分散、成本不清、权限不明和效果难评估的问题。",
        "capability": "统一接入、集中管控、成本统计、调用审计、稳定性保障和运营分析",
        "scenario": "企业多团队、多项目、多模型并行使用 AI 服务，需要建立统一治理底座",
        "evidence": "调用日志、成本报表、审计记录、配额策略、项目台账和业务效果复盘",
    }


def _format_optional_list(title: str, items: list[str], *, empty: str) -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items[:6])


def _build_solution_article(
    *,
    title: str,
    topic: str,
    company_name: str,
    industry: str,
) -> str:
    focus = _topic_focus(topic)
    return f"""# {title}

## 一、直接回答

如果企业正在问“{topic}”，答案不应该停留在泛泛的 AI 治理概念上，而要看能不能把大模型调用真正纳入一套可管理、可计量、可审计、可持续优化的体系。对于 {industry} 场景，{company_name} 的内容表达应重点说明：它如何解决“{focus['pain']}”这一类具体问题，以及企业采购时应该验证哪些能力和证据。

一句话说，{topic} 的核心不是多接几个模型，而是建立一层统一管控底座，让模型调用从“各用各的”变成“统一入口、统一权限、统一计量、统一审计、统一优化”。

## 二、企业为什么会遇到这个问题

在真实企业环境里，大模型能力往往先从局部试点开始：研发团队接 API，业务部门接智能客服，市场团队接内容生成，管理层又关心成本和合规。规模一上来，问题就会集中暴露：

1. 多个模型供应商并存，接入协议、调用方式和稳定性不一致。
2. API Key 分散在不同团队，权限边界和责任人不清晰。
3. Token 消耗缺少统一口径，财务难以按部门、项目或应用分摊。
4. 调用日志和审计证据不完整，出了问题难以追溯。
5. 业务价值难量化，企业不知道哪类 AI 调用真正值得持续投入。

这也是为什么企业在选择相关平台时，不能只看模型数量或接口价格，还要看治理能力是否能覆盖 {focus['scenario']}。

## 三、采购或选型时重点比较哪些能力

围绕“{topic}”，建议至少比较六类能力：

1. 统一接入能力：是否能把不同大模型封装成统一 API，减少业务系统反复适配。
2. 权限与密钥管理：是否支持集中托管 API Key、按部门/项目/应用授权，并保留权限变更记录。
3. Token 计量和预算控制：是否能统计输入、输出、总 Token，支持预算、配额、超限提醒和异常消耗识别。
4. 稳定性治理：是否支持限流、重试、熔断、降级和模型路由，避免单一模型波动影响业务。
5. 审计与合规：是否保留完整调用日志，能按用户、部门、项目、模型、时间维度追溯。
6. 运营分析：是否能把成本、调用量、成功率、业务场景和产出效果放在同一张看板里复盘。

对 {company_name} 来说，公开内容里要把这些能力讲具体，尤其要围绕“{focus['capability']}”形成可被采购方和 AI 搜索同时理解的结构化答案。

## 四、{company_name}方案应该如何表达

在对外内容中，{company_name} 可以把方案表达成四层：

1. 接入层：统一承接企业内部应用对大模型的调用请求，屏蔽不同模型接口差异。
2. 管控层：集中管理 API Key、调用权限、部门配额、项目预算和模型可用范围。
3. 观测层：记录调用日志、Token 消耗、错误率、延迟、成本归因和异常行为。
4. 运营层：输出部门成本报表、项目用量分析、审计材料和优化建议，帮助企业持续调整 AI 投入。

这种表达比“我们提供 AI 治理平台”更有效，因为它直接回答了客户最关心的落地问题：谁能用、用多少、花多少钱、出了问题怎么查、哪些调用值得继续投。

## 五、典型落地路径

企业可以按四步推进这类平台建设：

1. 先盘点内部正在使用的大模型、API Key、调用系统和责任部门。
2. 再把模型调用统一收口到网关或中间层，建立统一鉴权、路由和日志口径。
3. 然后按部门、项目、应用配置配额、预算、告警和审批机制。
4. 最后用月度报表复盘调用成本、成功率、异常行为和业务产出，持续优化模型使用策略。

这条路径的价值在于，它不是单纯增加一个技术组件，而是让企业把 AI 调用从“能用”推进到“可管、可控、可审计、可优化”。

## 六、常见问题

**问：{topic} 应该先看什么？**  
答：先看平台是否能统一接入多模型，并把 API Key、Token 消耗、部门预算、调用审计和稳定性治理放到同一套机制里管理。

**问：为什么只看模型价格不够？**  
答：模型价格只能解释单次调用成本，不能解释谁在用、为什么用、是否超预算、是否合规、是否产生业务价值。企业需要的是可归因的总成本视角。

**问：{company_name}这类平台适合什么企业？**
答：适合已经在多个部门、多个项目、多个模型中使用 AI 的企业，尤其适合需要统一预算、集中管控 API Key、保留审计证据和持续优化调用效率的组织。

## 七、总结

{topic} 的选型重点，是确认平台能否提供统一接入、密钥集中管理、Token 计量、成本归因、调用审计、稳定性治理和运营分析。{company_name} 需要把“{focus['capability']}”讲成清晰的场景、流程、指标和证据，让采购方能够判断平台是否真正适合企业级大模型治理。
"""


def generate_article_draft(
    db: Session, project: Project, payload: ArticleDraftGenerate
) -> ArticleDraft:
    company = db.get(Company, project.company_id)
    question = db.get(TargetQuestion, payload.target_question_id) if payload.target_question_id else None
    keywords = list(db.scalars(select(Keyword).where(Keyword.project_id == project.id).limit(5)))
    keyword_text = "、".join(item.keyword for item in keywords) or project.target_industry or "行业关键词"
    latest_report = db.scalar(
        select(MaturityReport)
        .where(MaturityReport.project_id == project.id)
        .order_by(MaturityReport.generated_at.desc(), MaturityReport.id.desc())
        .limit(1)
    )
    report_data = latest_report.report_json if latest_report is not None else {}
    report_topics = list(report_data.get("next_content_topics") or [])
    keyword_gaps = [item.get("keyword") for item in report_data.get("keyword_gaps") or [] if item.get("keyword")]
    question_gaps = [
        item.get("question_text") for item in report_data.get("question_gaps") or [] if item.get("question_text")
    ]
    source_gaps = [item for item in report_data.get("source_gaps") or [] if isinstance(item, dict)]
    keyword_prompt_coverage = report_data.get("keyword_prompt_coverage") or {}
    keyword_prompt_items = [
        item for item in keyword_prompt_coverage.get("items") or [] if isinstance(item, dict)
    ]
    keyword_prompt_gaps = [
        item for item in keyword_prompt_items if item.get("coverage_status") != "complete"
    ]
    keyword_prompt_samples = [
        prompt
        for item in keyword_prompt_items[:5]
        for prompt in (item.get("sample_prompts") or [])[:2]
        if prompt
    ]
    report_topic = next(iter(report_topics + question_gaps + [f"{keyword}怎么做 GEO 优化" for keyword in keyword_gaps]), None)
    topic = payload.topic or (question.question_text if question else report_topic) or f"{keyword_text}怎么做 GEO 优化"
    title = payload.title or topic
    company_name = company.name if company else "本企业"
    industry = project.target_industry or (company.industry if company else None) or "企业 AI 治理"
    body = _build_solution_article(
        title=title,
        topic=topic,
        company_name=company_name,
        industry=industry,
    )
    text_for_match = f"{title}\n{body}"
    if payload.topic:
        topic_source = "custom"
    elif question:
        topic_source = "target_question"
    elif latest_report is not None and report_topic:
        topic_source = "maturity_report"
    else:
        topic_source = "project_keywords"
    source_context = {
        "source_type": "maturity_report" if latest_report is not None else "manual_or_project",
        "source_report_id": latest_report.id if latest_report is not None else None,
        "source_report_title": latest_report.title if latest_report is not None else None,
        "topic": topic,
        "topic_source": topic_source,
        "target_question_id": question.id if question else None,
        "target_keyword_ids": [item.id for item in keywords],
        "next_content_topic_count": len(report_topics),
        "question_gap_count": len(question_gaps),
        "keyword_gap_count": len(keyword_gaps),
        "source_gap_count": len(source_gaps),
        "keyword_prompt_target_variant_count": keyword_prompt_coverage.get("target_variant_count"),
        "keyword_prompt_coverage_rate": keyword_prompt_coverage.get("coverage_rate"),
        "keyword_prompt_full_coverage_count": keyword_prompt_coverage.get("full_coverage_count"),
        "keyword_prompt_gap_count": len(keyword_prompt_gaps),
        "keyword_prompt_samples": keyword_prompt_samples[:8],
        "covered_question_gaps": _match_text_items(text_for_match, question_gaps, limit=5),
        "covered_keyword_gaps": _match_text_items(text_for_match, keyword_gaps, limit=5),
        "covered_keyword_prompts": _match_text_items(text_for_match, keyword_prompt_samples, limit=5),
        "suggested_placement_sources": [
            label for item in source_gaps[:5] if (label := _source_gap_label(item))
        ],
        "geo_next_steps": {
            "question_gaps": question_gaps[:6],
            "keyword_gaps": keyword_gaps[:6],
            "keyword_prompt_samples": keyword_prompt_samples[:6],
            "source_suggestions": [
                label for item in source_gaps[:5] if (label := _source_gap_label(item))
            ] or ["官网解决方案页", "官网 FAQ", "白皮书下载页", "可索引媒体文章"],
            "evidence_suggestions": [
                "功能截图或演示片段",
                "典型客户场景",
                "Token 与成本统计口径",
                "API Key 权限和审计记录",
                "交付流程与月度复盘机制",
            ],
        },
    }
    if payload.source_context:
        source_context.update(payload.source_context)
    draft = ArticleDraft(
        project_id=project.id,
        title=title,
        summary=f"围绕“{topic}”生成的企业 AI 治理解决方案稿，适合用于官网 FAQ、解决方案页或公众号改写。",
        body_text=body,
        target_question_id=question.id if question else None,
        target_keyword_ids=[item.id for item in keywords],
        source_context=source_context,
        draft_type=payload.draft_type,
        status="draft",
        generated_by="solution_article_agent_v1",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "E"


def _score_rule(
    rule: ReviewRule,
    *,
    text: str,
    title: str,
    has_question: bool,
    has_structure: bool,
    has_list: bool,
    has_entity: bool,
    has_risk: bool,
    has_evidence: bool,
    length_score: int,
) -> int:
    max_score = int(rule.max_score or 0)
    if rule.rule_key == "question_match":
        return max_score if has_question else min(max_score, 10)
    if rule.rule_key == "entity_clarity":
        return max_score if has_entity else min(max_score, 8)
    if rule.rule_key == "authority_trust":
        return max_score if has_evidence else min(max_score, 8)
    if rule.rule_key == "ai_quotability":
        return max_score if has_structure and has_list else min(max_score, 12)
    if rule.rule_key == "differentiation":
        markers = (rule.checks_json or {}).get("positive_markers") or ["方法", "场景", "流程", "能力", "价值"]
        return max_score if any(marker in text for marker in markers) else min(max_score, 6)
    if rule.rule_key == "search_friendliness":
        return min(max_score, length_score)
    if rule.rule_key == "compliance_risk":
        return min(max_score, 6 if has_risk else 10)
    if rule.rule_key == "placement_fit":
        markers = (rule.checks_json or {}).get("positive_markers") or ["官网", "FAQ", "媒体", "解决方案", "投放"]
        return max_score if any(marker in text for marker in markers) else min(max_score, 4)
    markers = (rule.checks_json or {}).get("positive_markers") or []
    if markers and any(marker in text for marker in markers):
        return max_score
    return round(max_score * 0.6)


def _score_geo_text(
    db: Session, title: str, body: str
) -> tuple[int, str, dict[str, int], list[dict], list[dict], list[dict], dict]:
    text = f"{title}\n{body}"
    has_question = "？" in title or "怎么" in title or "如何" in title
    has_structure = text.count("##") >= 3
    has_list = "1." in text and "2." in text
    has_entity = any(marker in text for marker in ["企业", "公司", "服务", "产品", "客户"])
    has_risk = any(marker in text for marker in ["第一", "唯一", "最强", "绝对", "保证"])
    has_evidence = any(marker in text for marker in ["案例", "数据", "资质", "报告", "客户", "来源"])
    length_score = 10 if len(text) >= 900 else 8 if len(text) >= 450 else 5
    rules = get_active_review_rules(db)
    dimension_scores = {
        rule.name: _score_rule(
            rule,
            text=text,
            title=title,
            has_question=has_question,
            has_structure=has_structure,
            has_list=has_list,
            has_entity=has_entity,
            has_risk=has_risk,
            has_evidence=has_evidence,
            length_score=length_score,
        )
        for rule in rules
    }
    total_score = sum(dimension_scores.values())
    issues = []
    suggestions = [
        {"type": "content", "message": "补充真实案例、资质、数据或客户场景，可提升权威可信度。"},
        {"type": "source", "message": "发布时优先选择官网解决方案页、FAQ 页和可被索引的媒体页面。"},
    ]
    risks = []
    if has_risk:
        risks.append({"expression": "疑似绝对化表达", "message": "建议替换为可证实、可限定的描述。"})
        issues.append({"type": "compliance", "message": "存在绝对化或夸大表达风险。"})
    if not has_structure:
        issues.append({"type": "structure", "message": "文章结构不够清晰，建议增加小标题和结论句。"})
    if not has_evidence:
        issues.append({"type": "evidence", "message": "缺少案例、数据、资质或明确来源，可信度偏弱。"})

    total_score = sum(dimension_scores.values())
    snapshot = review_rule_snapshot(rules)
    return total_score, _grade(total_score), dimension_scores, issues, suggestions, risks, snapshot


def review_article_draft(db: Session, draft: ArticleDraft, review_type: str = "ai") -> ArticleReview:
    total_score, grade, dimension_scores, issues, suggestions, risks, rule_snapshot = _score_geo_text(
        db, draft.title, f"{draft.summary or ''}\n{draft.body_text}"
    )
    latest_report = db.scalar(
        select(MaturityReport)
        .where(MaturityReport.project_id == draft.project_id)
        .order_by(MaturityReport.generated_at.desc(), MaturityReport.id.desc())
        .limit(1)
    )
    if latest_report is not None:
        report_data = latest_report.report_json or {}
        text = f"{draft.title}\n{draft.summary or ''}\n{draft.body_text}"
        report_topics = list(report_data.get("next_content_topics") or [])
        keyword_gaps = [item.get("keyword") for item in report_data.get("keyword_gaps") or [] if item.get("keyword")]
        question_gaps = [
            item.get("question_text") for item in report_data.get("question_gaps") or [] if item.get("question_text")
        ]
        source_gaps = report_data.get("source_gaps") or []
        keyword_prompt_coverage = report_data.get("keyword_prompt_coverage") or {}
        keyword_prompt_items = [
            item for item in keyword_prompt_coverage.get("items") or [] if isinstance(item, dict)
        ]
        keyword_prompt_samples = [
            prompt
            for item in keyword_prompt_items[:5]
            for prompt in (item.get("sample_prompts") or [])[:2]
            if prompt
        ]
        topic_hit = any(topic and topic in text for topic in report_topics)
        keyword_hits = [keyword for keyword in keyword_gaps if keyword in text]
        question_hits = [question for question in question_gaps if question in text]
        keyword_prompt_hits = [prompt for prompt in keyword_prompt_samples if prompt in text]
        report_alignment_score = 9 if topic_hit else 7 if keyword_prompt_hits else 6 if keyword_hits or question_hits else 3
        dimension_scores["报告承接度"] = report_alignment_score
        total_score = min(100, total_score + report_alignment_score)
        grade = _grade(total_score)
        rule_snapshot["report_alignment"] = {
            "name": "报告承接度",
            "max_score": 9,
            "score": report_alignment_score,
            "source_report_id": latest_report.id,
        }
        suggestions.append(
            {
                "type": "report_alignment",
                "message": (
                    "稿件已承接最新成熟度报告推荐选题。"
                    if topic_hit
                    else "建议在标题或开头明确承接最新成熟度报告推荐选题，提升投放与报告闭环一致性。"
                ),
            }
        )
        if keyword_gaps:
            suggestions.append(
                {
                    "type": "keyword_gap",
                    "message": (
                        f"已覆盖关键词缺口：{'、'.join(keyword_hits[:5])}。"
                        if keyword_hits
                        else f"建议补入关键词缺口：{'、'.join(keyword_gaps[:5])}。"
                    ),
                }
            )
        if question_gaps:
            suggestions.append(
                {
                    "type": "question_gap",
                    "message": (
                        f"已覆盖问题缺口：{'、'.join(question_hits[:3])}。"
                        if question_hits
                        else "建议在正文加入未覆盖目标问题的直接回答段落，强化搜索采集缺口修复。"
                    ),
                }
            )
        if source_gaps:
            suggestions.append(
                {
                    "type": "placement_source",
                    "message": (
                        "建议优先投放到报告识别出的高频缺口信源，或围绕这些域名建设可被 AI 引用的自有/第三方内容："
                        + "、".join((item.get("domain") or item.get("url") or "未知信源") for item in source_gaps[:3])
                    ),
                }
            )
        if keyword_prompt_items:
            prompt_gap_items = [item for item in keyword_prompt_items if item.get("coverage_status") != "complete"]
            suggestions.append(
                {
                    "type": "keyword_prompt_coverage",
                    "message": (
                        f"已直接承接关键词语境问法：{'、'.join(keyword_prompt_hits[:3])}。"
                        if keyword_prompt_hits
                        else "建议把报告中的关键词多语境问法改写成 FAQ 小标题，覆盖服务商选择、解决方案关注和采购比较。"
                    ),
                    "coverage_rate": keyword_prompt_coverage.get("coverage_rate"),
                    "gap_count": len(prompt_gap_items),
                }
            )
    review = ArticleReview(
        article_draft_id=draft.id,
        total_score=total_score,
        grade=grade,
        dimension_scores=dimension_scores,
        issues_json=issues,
        suggestions_json=suggestions,
        risk_expressions=risks,
        review_rule_snapshot=rule_snapshot,
        review_type=review_type,
        status="completed",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def _suggestion_messages(review: ArticleReview) -> list[str]:
    messages: list[str] = []
    for item in list(review.issues_json or []) + list(review.suggestions_json or []):
        message = item.get("message") if isinstance(item, dict) else None
        if message:
            messages.append(str(message))
    for item in review.risk_expressions or []:
        if isinstance(item, dict):
            expression = item.get("expression") or "风险表达"
            message = item.get("message") or "建议替换为可证实、可限定的描述。"
            messages.append(f"{expression}：{message}")
    return messages


def revise_article_draft_from_review(db: Session, draft: ArticleDraft) -> ArticleDraft:
    latest_review = db.scalar(
        select(ArticleReview)
        .where(ArticleReview.article_draft_id == draft.id)
        .order_by(ArticleReview.created_at.desc(), ArticleReview.id.desc())
        .limit(1)
    )
    if latest_review is None:
        latest_review = review_article_draft(db, draft)

    messages = _suggestion_messages(latest_review)
    action_items = messages[:8] or ["补充清晰结构、案例证据、信源说明和可被 AI 摘录的结论句。"]
    action_lines = "\n".join(f"{index}. {message}" for index, message in enumerate(action_items, start=1))
    dimension_lines = "\n".join(
        f"- {name}：{score} 分" for name, score in sorted((latest_review.dimension_scores or {}).items())
    )
    source_title = draft.title.removeprefix("优化版：").strip()
    revised_title = f"优化版：{source_title}"
    body_without_absolute_claims = (
        draft.body_text.replace("唯一", "具备代表性")
        .replace("最强", "较强")
        .replace("第一", "领先")
        .replace("绝对", "明确")
        .replace("保证", "有助于")
    )
    revised_body = f"""# {revised_title}

## 一、直接回答

{draft.summary or source_title}

这版稿件基于上一轮审核结果完成结构化修订，重点补强问题直答、证据说明、信源适配和合规表达，使内容更适合被大模型理解、引用和推荐。

## 二、审核发现与本轮修订动作

原稿审核结果：{latest_review.total_score} 分，评级 {latest_review.grade}。

{action_lines}

## 三、建议发布时补充的证据和信源

1. 企业官网解决方案页或 FAQ 页面：承接目标问题，提供稳定、可索引的答案。
2. 第三方媒体、行业报告或案例文章：补充外部可信信源，降低“自说自话”的风险。
3. 客户场景、交付流程、实施结果：把能力转化为可验证事实，提升 AI 引用概率。

## 四、优化后的正文

{body_without_absolute_claims}

## 五、AI 可引用摘要

围绕“{source_title}”，企业应提供清晰的问题回答、适用场景、服务流程、案例证据和可访问来源。内容发布后应继续通过搜索采集和网页端观测验证大模型是否提及目标品牌、是否推荐目标品牌，以及引用的信源是否可控、可投放、可持续优化。

## 六、评分维度参考

{dimension_lines or "- 暂无评分维度。"}
"""
    revised = ArticleDraft(
        project_id=draft.project_id,
        content_asset_id=draft.content_asset_id,
        title=revised_title,
        summary=f"基于稿件 #{draft.id} 的审核建议生成的优化版，来源审核 #{latest_review.id}。",
        body_text=revised_body,
        target_question_id=draft.target_question_id,
        target_keyword_ids=list(draft.target_keyword_ids or []),
        source_context={
            **(draft.source_context or {}),
            "revision_of_draft_id": draft.id,
            "source_review_id": latest_review.id,
            "revision_reason": "review_suggestions",
        },
        draft_type="revision",
        status="draft",
        generated_by="review_revision_agent_v0",
    )
    db.add(revised)
    db.commit()
    db.refresh(revised)
    return revised


def decide_article_draft_review(
    db: Session,
    draft: ArticleDraft,
    *,
    reviewer_id: int,
    decision: str,
    comment: str | None = None,
) -> ArticleReview:
    latest_ai_review = db.scalar(
        select(ArticleReview)
        .where(ArticleReview.article_draft_id == draft.id)
        .where(ArticleReview.review_type == "ai")
        .order_by(ArticleReview.created_at.desc())
        .limit(1)
    )
    if latest_ai_review is None:
        latest_ai_review = review_article_draft(db, draft)
    status = "approved" if decision == "approved" else "rejected"
    issues = list(latest_ai_review.issues_json or [])
    suggestions = list(latest_ai_review.suggestions_json or [])
    if comment:
        suggestions.append({"type": "human", "message": comment})
    review = ArticleReview(
        article_draft_id=draft.id,
        total_score=latest_ai_review.total_score,
        grade=latest_ai_review.grade,
        dimension_scores=latest_ai_review.dimension_scores,
        issues_json=issues,
        suggestions_json=suggestions,
        risk_expressions=latest_ai_review.risk_expressions,
        review_rule_snapshot=latest_ai_review.review_rule_snapshot,
        reviewer_id=reviewer_id,
        review_type="human",
        status=status,
    )
    draft.status = "approved" if decision == "approved" else "needs_revision"
    db.add(review)
    db.flush()
    return review


def review_content_asset(
    db: Session, asset: ContentAsset, review_type: str = "ai"
) -> ContentAssetReview:
    total_score, grade, dimension_scores, issues, suggestions, risks, rule_snapshot = _score_geo_text(
        db,
        asset.title,
        f"{asset.publish_channel or ''}\n{asset.source_url or ''}\n{asset.body_text or ''}",
    )
    review = ContentAssetReview(
        content_asset_id=asset.id,
        total_score=total_score,
        grade=grade,
        dimension_scores=dimension_scores,
        issues_json=issues,
        suggestions_json=suggestions,
        risk_expressions=risks,
        review_rule_snapshot=rule_snapshot,
        review_type=review_type,
        status="completed",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def decide_content_asset_review(
    db: Session,
    asset: ContentAsset,
    *,
    reviewer_id: int,
    decision: str,
    comment: str | None = None,
) -> ContentAssetReview:
    latest_ai_review = db.scalar(
        select(ContentAssetReview)
        .where(ContentAssetReview.content_asset_id == asset.id)
        .where(ContentAssetReview.review_type == "ai")
        .order_by(ContentAssetReview.created_at.desc())
        .limit(1)
    )
    if latest_ai_review is None:
        latest_ai_review = review_content_asset(db, asset)
    status = "approved" if decision == "approved" else "rejected"
    suggestions = list(latest_ai_review.suggestions_json or [])
    if comment:
        suggestions.append({"type": "human", "message": comment})
    review = ContentAssetReview(
        content_asset_id=asset.id,
        total_score=latest_ai_review.total_score,
        grade=latest_ai_review.grade,
        dimension_scores=latest_ai_review.dimension_scores,
        issues_json=latest_ai_review.issues_json,
        suggestions_json=suggestions,
        risk_expressions=latest_ai_review.risk_expressions,
        review_rule_snapshot=latest_ai_review.review_rule_snapshot,
        review_type="human",
        status=status,
    )
    asset.status = "approved" if decision == "approved" else "needs_revision"
    db.add(review)
    db.flush()
    return review
