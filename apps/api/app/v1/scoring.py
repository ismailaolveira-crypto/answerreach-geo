from __future__ import annotations

from hashlib import sha256
import re

from app.models.cleanroom_v1 import GeoEvidence


# Based on the MIT-licensed HeiGe GEO-SEO scoring-card methodology.  This is a
# clean-room, content-snapshot implementation: unavailable technical signals are
# reported as unavailable instead of being guessed as a pass.
SCORING_VERSION = "heige-deterministic-geo-audit/1.1"


def score_evidence(evidence: list[GeoEvidence]) -> tuple[dict, dict, str]:
    eligible = [item for item in evidence if item.is_real_provider_evidence and item.evidence_level == "auditable"]
    # Natural visibility means that the brand appeared, regardless of whether
    # the context was favorable. Negative mentions remain separately visible
    # and must not silently disappear from the numerator.
    mentioned = [item for item in eligible if item.brand_status in {"mentioned", "shortlisted", "recommended", "cited", "negative"}]
    negative_mentions = [item for item in eligible if item.brand_status == "negative"]
    shortlisted = [
        item for item in eligible
        if item.brand_status in {"shortlisted", "recommended"}
        or (item.brand_position is not None and item.brand_position <= 3)
    ]
    cited = [item for item in eligible if item.brand_status == "cited"]
    sourced = [item for item in eligible if item.source_items]
    ranked = [item for item in eligible if item.brand_position is not None]
    fingerprint = sha256("|".join(sorted(item.answer_hash for item in evidence)).encode()).hexdigest()
    total = len(eligible)
    def ratio(rows: list[GeoEvidence]) -> float:
        return round(len(rows) * 100 / total, 2) if total else 0.0
    metrics = {
        "eligible_samples": total,
        "all_samples": len(evidence),
        "excluded_samples": len(evidence) - total,
        "mention_count": len(mentioned),
        "negative_mention_count": len(negative_mentions),
        "mention_rate": ratio(mentioned),
        "shortlist_count": len(shortlisted),
        "shortlist_rate": ratio(shortlisted),
        "citation_count": len(cited),
        "citation_rate": ratio(cited),
        "source_coverage_rate": ratio(sourced),
        "top1_rate": ratio([item for item in ranked if item.brand_position == 1]),
        "top3_rate": ratio([item for item in ranked if item.brand_position and item.brand_position <= 3]),
        "top5_rate": ratio([item for item in ranked if item.brand_position and item.brand_position <= 5]),
        "average_rank": round(sum(item.brand_position for item in ranked if item.brand_position) / len(ranked), 2) if ranked else None,
    }
    explanation = {
        "rule_engine": SCORING_VERSION,
        "eligibility": "only auditable authorized API or browser-assisted evidence is included; mock, partial, and manual records are retained but excluded",
        "source_metrics": "citation rate requires a brand-owned source citation; source coverage separately measures any visible source items",
    }
    return metrics, explanation, fingerprint


def audit_content_snapshot(title: str, body: str, source_urls: list[str]) -> dict:
    """Deterministic subset of HeiGe's 6-dimension GEO citation-readiness card.

    This function deliberately does not fabricate robots/WAF/schema validity from a
    pasted snapshot. Those checks stay `unavailable` until the URL audit adapter
    supplies actual HTTP/HTML evidence.
    """
    text = body.strip()
    lower = text.lower()
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text)
    sentences = [part.strip() for part in re.split(r"[。！？!?\n]+", text) if part.strip()]
    valid_sources = [url for url in source_urls if url.startswith(("https://", "http://"))]
    heading_count = len(re.findall(r"(?m)^#{2,}\s+|<h[23][^>]*>", text))
    list_or_table = bool(re.search(r"(?m)^\s*(?:[-*+]\s+|\d+[.)、])|\|.+\|", text))
    numeric_claims = len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|个|项|倍|天|年|家|条|人|万|亿)?", text))
    claim_density = round(numeric_claims * 100 / max(len(words), 1), 2)
    answer_first = bool(re.search(r"\d|是|可|支持|提供|建议|适合", text[:240]))
    average_sentence_length = round(len(words) / max(len(sentences), 1), 2)
    faq = "faq" in lower or "常见问题" in text or "问：" in text or "q:" in lower
    schema = "faqpage" in lower or "application/ld+json" in lower or "@context" in lower
    checks = {
        # A: capture adapters must provide the real crawlability verdict later.
        "crawler_access": "unavailable",
        # B: discovery file is URL-level evidence, not a body-text guess.
        "ai_discovery_files": "unavailable",
        # C: structured data
        "faq_schema_or_jsonld": schema,
        "faq_structure": faq,
        # D: answer extractability
        "answer_first": answer_first,
        "claim_density_per_100_tokens": claim_density,
        "claim_density_pass": claim_density >= 4,
        "sentence_length_tokens": average_sentence_length,
        "sentence_structure_pass": 8 <= average_sentence_length <= 32,
        "information_density_pass": 800 <= len(words) <= 1800,
        "data_and_sources": numeric_claims > 0 and bool(valid_sources),
        # E: parseable content shape
        "heading_structure": heading_count >= 2,
        "list_or_table": list_or_table,
        "definition_or_qa_block": faq or bool(re.search(r"是什么|如何|怎么", text)),
        # F: only claim what is visible in the supplied snapshot.
        "author_or_person_markup": "author" in lower or "作者" in text,
        "entity_consistency": bool(title.strip()) and any(token in text for token in re.findall(r"[\u4e00-\u9fff]{2,}", title)),
        "external_evidence_sources": len(valid_sources),
    }
    weighted = {
        "faq_schema_or_jsonld": 6, "faq_structure": 3,
        "answer_first": 5, "claim_density_pass": 6, "sentence_structure_pass": 3,
        "information_density_pass": 4, "data_and_sources": 4,
        "heading_structure": 4, "list_or_table": 3, "definition_or_qa_block": 3,
        "author_or_person_markup": 3, "entity_consistency": 3, "external_evidence_sources": 3,
    }
    raw_score = sum(weight for key, weight in weighted.items() if checks[key])
    scored_weight = sum(weighted.values())
    return {
        "engine": SCORING_VERSION,
        "score": round(raw_score * 100 / scored_weight, 2),
        "checks": checks,
        "scored_weight": scored_weight,
        "raw_score": raw_score,
        "unavailable_dimensions": ["crawler_access", "ai_discovery_files"],
    }
