from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReportTemplate


DEFAULT_REPORT_TEMPLATE = {
    "template_key": "geo_maturity_standard_v1",
    "name": "GEO 成熟度诊断标准模板",
    "description": "用于客户 GEO 成熟度报告的默认章节、评分维度和交付质量门槛。",
    "applies_to": "maturity_report",
    "sections_json": [
        {"key": "summary", "title": "摘要", "required": True},
        {"key": "core_metrics", "title": "核心指标", "required": True},
        {"key": "coverage", "title": "覆盖摘要", "required": True},
        {"key": "evidence_quality", "title": "样本可信度", "required": True},
        {"key": "delivery_readiness", "title": "交付就绪度", "required": True},
        {"key": "score_items", "title": "评分明细", "required": True},
        {"key": "brand_matrix", "title": "品牌推荐矩阵", "required": True},
        {"key": "evidence_appendix", "title": "证据样本附录", "required": True},
        {"key": "recommendations", "title": "优化建议", "required": True},
    ],
    "scoring_json": {
        "total_score": 100,
        "dimensions": [
            {"key": "visibility", "name": "AI 可见度", "max_score": 20},
            {"key": "recommendation", "name": "AI 推荐度", "max_score": 20},
            {"key": "competitor", "name": "竞品竞争力", "max_score": 15},
            {"key": "source_health", "name": "信源健康度", "max_score": 15},
            {"key": "content_maturity", "name": "内容资产成熟度", "max_score": 15},
            {"key": "coverage", "name": "问题覆盖度", "max_score": 10},
            {"key": "risk", "name": "风险可控性", "max_score": 5},
        ],
        "levels": [
            {"level": "L5 行业权威", "min_score": 81},
            {"level": "L4 稳定推荐", "min_score": 61},
            {"level": "L3 可被识别", "min_score": 41},
            {"level": "L2 偶发可见", "min_score": 21},
            {"level": "L1 不可见", "min_score": 0},
        ],
    },
    "delivery_checks_json": [
        {"key": "sample_size", "label": "样本量", "required": 20},
        {"key": "provider_coverage", "label": "模型覆盖", "required": 3},
        {"key": "question_coverage", "label": "目标问题覆盖", "required": 0.8},
        {"key": "keyword_coverage", "label": "关键词覆盖", "required": 0.8},
        {"key": "traceable_evidence", "label": "证据可追溯", "required": 3},
        {"key": "browser_evidence", "label": "网页端/截图留证", "required": 1},
        {"key": "brand_matrix", "label": "品牌推荐矩阵", "required": 2},
        {"key": "actionable_recommendations", "label": "可执行建议", "required": 3},
    ],
    "status": "active",
    "version": 1,
}


def seed_default_report_template(db: Session) -> ReportTemplate:
    existing = db.scalar(
        select(ReportTemplate).where(
            ReportTemplate.template_key == DEFAULT_REPORT_TEMPLATE["template_key"]
        )
    )
    if existing is None:
        existing = ReportTemplate(**DEFAULT_REPORT_TEMPLATE)
        db.add(existing)
        db.commit()
        db.refresh(existing)
    return existing


def get_active_report_template(
    db: Session, applies_to: str = "maturity_report"
) -> ReportTemplate:
    template = db.scalar(
        select(ReportTemplate)
        .where(ReportTemplate.status == "active")
        .where(ReportTemplate.applies_to.in_([applies_to, "all"]))
        .order_by(ReportTemplate.version.desc(), ReportTemplate.id.asc())
    )
    if template is not None:
        return template
    return seed_default_report_template(db)


def report_template_snapshot(template: ReportTemplate) -> dict:
    return {
        "id": template.id,
        "template_key": template.template_key,
        "name": template.name,
        "description": template.description,
        "applies_to": template.applies_to,
        "version": template.version,
        "status": template.status,
        "sections": template.sections_json or [],
        "scoring": template.scoring_json or {},
        "delivery_checks": template.delivery_checks_json or [],
    }
