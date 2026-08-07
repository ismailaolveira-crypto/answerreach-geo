from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReviewRule


DEFAULT_REVIEW_RULES = [
    {
        "rule_key": "question_match",
        "name": "问题命中度",
        "description": "标题和开头是否直接承接目标问题，能否被 AI 识别为问题答案。",
        "max_score": 14,
        "checks_json": {"positive_markers": ["？", "怎么", "如何"]},
    },
    {
        "rule_key": "entity_clarity",
        "name": "实体清晰度",
        "description": "企业、产品、服务、客户和行业实体是否表达清楚。",
        "max_score": 14,
        "checks_json": {"positive_markers": ["企业", "公司", "服务", "产品", "客户"]},
    },
    {
        "rule_key": "authority_trust",
        "name": "权威可信度",
        "description": "是否包含案例、数据、资质、报告、客户或来源证据。",
        "max_score": 13,
        "checks_json": {"positive_markers": ["案例", "数据", "资质", "报告", "客户", "来源"]},
    },
    {
        "rule_key": "ai_quotability",
        "name": "AI 可引用性",
        "description": "结构是否清晰，是否便于大模型摘录为答案片段。",
        "max_score": 18,
        "checks_json": {"requires_headings": 3, "requires_ordered_list": True},
    },
    {
        "rule_key": "differentiation",
        "name": "差异化价值",
        "description": "是否有清晰方法、场景或服务价值，而不是泛泛宣传。",
        "max_score": 8,
        "checks_json": {"positive_markers": ["方法", "场景", "流程", "能力", "价值"]},
    },
    {
        "rule_key": "search_friendliness",
        "name": "搜索友好度",
        "description": "正文长度和关键词密度是否支撑检索、索引和复用。",
        "max_score": 10,
        "checks_json": {"excellent_length": 900, "good_length": 450},
    },
    {
        "rule_key": "compliance_risk",
        "name": "合规风险",
        "description": "是否规避绝对化、夸大或不可验证表达。",
        "max_score": 10,
        "checks_json": {"risk_markers": ["第一", "唯一", "最强", "绝对", "保证"]},
    },
    {
        "rule_key": "placement_fit",
        "name": "投放适配度",
        "description": "是否适合官网、FAQ、媒体稿或解决方案页等可采信页面投放。",
        "max_score": 4,
        "checks_json": {"positive_markers": ["官网", "FAQ", "媒体", "解决方案", "投放"]},
    },
]


def seed_default_review_rules(db: Session) -> list[ReviewRule]:
    existing_keys = set(db.scalars(select(ReviewRule.rule_key)))
    created: list[ReviewRule] = []
    for item in DEFAULT_REVIEW_RULES:
        if item["rule_key"] in existing_keys:
            continue
        rule = ReviewRule(
            rule_key=item["rule_key"],
            name=item["name"],
            description=item["description"],
            applies_to="article",
            max_score=item["max_score"],
            weight=1,
            checks_json=item["checks_json"],
            status="active",
            version=1,
        )
        db.add(rule)
        created.append(rule)
    if created:
        db.commit()
    return list(
        db.scalars(
            select(ReviewRule)
            .where(ReviewRule.status == "active")
            .order_by(ReviewRule.id.asc())
        )
    )


def get_active_review_rules(db: Session, applies_to: str = "article") -> list[ReviewRule]:
    rules = list(
        db.scalars(
            select(ReviewRule)
            .where(ReviewRule.status == "active")
            .where(ReviewRule.applies_to.in_([applies_to, "all"]))
            .order_by(ReviewRule.id.asc())
        )
    )
    if rules:
        return rules
    return seed_default_review_rules(db)


def review_rule_snapshot(rules: list[ReviewRule]) -> dict:
    return {
        "standard": "GEO 内容审核评分标准",
        "version": max((rule.version for rule in rules), default=1),
        "total_max_score": sum(int(rule.max_score or 0) for rule in rules),
        "rules": [
            {
                "id": rule.id,
                "rule_key": rule.rule_key,
                "name": rule.name,
                "max_score": rule.max_score,
                "weight": rule.weight,
                "version": rule.version,
                "checks": rule.checks_json or {},
            }
            for rule in rules
        ],
    }
