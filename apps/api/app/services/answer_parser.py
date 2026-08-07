import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerAnalysis,
    CitationSource,
    Company,
    ContentAsset,
    Competitor,
    CrawlResult,
    MentionedEntity,
    PlacementRecord,
)


def _count_name(text: str, name: str) -> int:
    if not name:
        return 0
    return text.lower().count(name.lower())


NEGATIVE_VISIBILITY_MARKERS = [
    "不会自然提到",
    "不会自然会提到",
    "不会提到",
    "未自然提到",
    "并未自然提到",
    "不应自然提到",
    "不会推荐",
    "不会作为推荐",
    "不会将其推荐",
    "不会把其推荐",
    "不会把它推荐",
    "不建议推荐",
    "无法推荐",
    "不具备推荐",
    "不会被推荐",
    "不作为候选",
    "未纳入候选",
    "缺少足够",
    "缺乏足够",
    "缺少公开信号",
    "缺乏公开信号",
    "公开信息不足",
    "未发现",
    "未查询到",
    "无法查询到",
    "未经验证",
    "不会虚构",
    "不虚构",
]

RECOMMENDATION_MARKERS = ["候选", "推荐", "可以作为", "优先考虑", "值得关注", "服务商包括"]


def _name_contexts(text: str, names: list[str], window: int = 80) -> list[str]:
    contexts: list[str] = []
    lower_text = text.lower()
    for name in names:
        if not name:
            continue
        lower_name = name.lower()
        start = 0
        while True:
            index = lower_text.find(lower_name, start)
            if index < 0:
                break
            left = max(0, index - window)
            right = min(len(text), index + len(name) + window)
            contexts.append(text[left:right])
            start = index + len(name)
    return contexts


def _is_negative_visibility_context(context: str) -> bool:
    normalized = re.sub(r"\s+", "", context)
    return any(marker in normalized for marker in NEGATIVE_VISIBILITY_MARKERS)


def _visibility_signals(text: str, company: Company) -> dict:
    names = [company.name, *company.brand_aliases]
    mention_count = _count_name(text, company.name)
    alias_count = sum(_count_name(text, alias) for alias in company.brand_aliases)
    contexts = _name_contexts(text, names)
    positive_contexts = [context for context in contexts if not _is_negative_visibility_context(context)]
    negative_contexts = [context for context in contexts if _is_negative_visibility_context(context)]
    positive_context_blob = "\n".join(positive_contexts)
    recommended = bool(positive_contexts) and any(marker in positive_context_blob for marker in RECOMMENDATION_MARKERS)
    return {
        "company_mentions": mention_count,
        "alias_mentions": alias_count,
        "raw_context_count": len(contexts),
        "positive_context_count": len(positive_contexts),
        "negative_context_count": len(negative_contexts),
        "negative_context_samples": negative_contexts[:3],
        "positive_context_samples": positive_contexts[:3],
        "company_mentioned": bool(positive_contexts),
        "company_recommended": recommended,
    }


def _extract_urls(text: str) -> list[str]:
    return [url.rstrip("，。,()[]<>") for url in re.findall(r"https?://[^\s，。,\]()<>]+", text)]


def _score_source_url(url: str) -> tuple[int, int]:
    parsed = urlparse(url)
    path = parsed.path.lower()
    is_https = parsed.scheme == "https"
    has_query_noise = bool(parsed.query)
    crawlable_score = 70 if is_https else 55
    if has_query_noise:
        crawlable_score -= 10
    if any(marker in path for marker in ["faq", "solution", "case", "article", "news", "report"]):
        ai_readiness_score = 78
    else:
        ai_readiness_score = 60
    if any(marker in path for marker in ["login", "paywall", "private"]):
        crawlable_score -= 25
        ai_readiness_score -= 20
    return max(0, min(100, crawlable_score)), max(0, min(100, ai_readiness_score))


def _domain_matches(url: str | None, domain: str) -> bool:
    return bool(url and urlparse(url).netloc == domain)


def analyze_answer(
    db: Session,
    result: CrawlResult,
    company: Company,
    competitors: list[Competitor],
) -> AnswerAnalysis:
    text = result.raw_answer
    signals = _visibility_signals(text, company)
    company_mentions = int(signals["company_mentions"])
    alias_mentions = int(signals["alias_mentions"])
    company_mentioned = bool(signals["company_mentioned"])
    company_recommended = bool(signals["company_recommended"])

    analysis = AnswerAnalysis(
        crawl_result_id=result.id,
        company_mentioned=company_mentioned,
        company_recommended=company_recommended,
        company_rank=1 if company_recommended else None,
        sentiment="positive" if company_recommended else "neutral",
        confidence=70 if company_mentioned else 45,
        analysis_json={
            "company_mentions": company_mentions,
            "alias_mentions": alias_mentions,
            "positive_context_count": signals["positive_context_count"],
            "negative_context_count": signals["negative_context_count"],
            "negative_context_samples": signals["negative_context_samples"],
            "positive_context_samples": signals["positive_context_samples"],
            "method": "rule_based_v0",
        },
    )
    db.add(analysis)

    if company_mentioned:
        db.add(
            MentionedEntity(
                crawl_result_id=result.id,
                entity_name=company.name,
                entity_type="company",
                is_company=True,
                mention_count=company_mentions + alias_mentions,
                recommendation_rank=1 if company_recommended else None,
                context_excerpt=result.answer_summary,
            )
        )

    for competitor in competitors:
        mention_count = _count_name(text, competitor.name) + sum(
            _count_name(text, alias) for alias in competitor.aliases
        )
        if mention_count > 0:
            competitor_contexts = _name_contexts(text, [competitor.name, *competitor.aliases])
            competitor_recommended = any(
                not _is_negative_visibility_context(context)
                and any(marker in context for marker in RECOMMENDATION_MARKERS)
                for context in competitor_contexts
            )
            db.add(
                MentionedEntity(
                    crawl_result_id=result.id,
                    entity_name=competitor.name,
                    entity_type="competitor",
                    is_competitor=True,
                    mention_count=mention_count,
                    recommendation_rank=1 if competitor_recommended else None,
                    context_excerpt=result.answer_summary,
                )
            )

    for url in _extract_urls(text):
        domain = urlparse(url).netloc
        matching_assets = list(
            db.scalars(
                select(ContentAsset)
                .where(ContentAsset.project_id == result.project_id)
                .where(ContentAsset.source_url.is_not(None))
            )
        )
        matching_placements = list(
            db.scalars(
                select(PlacementRecord)
                .where(PlacementRecord.project_id == result.project_id)
                .where(PlacementRecord.target_url.is_not(None))
            )
        )
        has_asset = any(_domain_matches(asset.source_url, domain) for asset in matching_assets)
        is_placed = any(_domain_matches(placement.target_url, domain) for placement in matching_placements)
        crawlable_score, ai_readiness_score = _score_source_url(url)
        if has_asset:
            ai_readiness_score = min(100, ai_readiness_score + 8)
        if is_placed:
            ai_readiness_score = min(100, ai_readiness_score + 7)
        db.add(
            CitationSource(
                crawl_result_id=result.id,
                source_url=url,
                source_domain=domain,
                source_type="web",
                is_owned=bool(company.website_url and domain in company.website_url),
                is_placed=is_placed,
                crawlable_score=crawlable_score,
                ai_readiness_score=ai_readiness_score,
            )
        )

    return analysis
