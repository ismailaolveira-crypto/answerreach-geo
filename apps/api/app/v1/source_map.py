from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models.cleanroom_v1 import GeoEvidence, GeoQuestionPlan


@dataclass(frozen=True)
class NormalizedSource:
    domain: str
    page_key: str
    canonical_url: str


@dataclass
class _Breakdown:
    citation_count: int = 0
    evidence_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class _EvidenceReference:
    """A source citation linked to the exact archived answer that produced it."""

    evidence_id: int
    source_url: str
    source_title: str | None = None


@dataclass
class _Aggregate:
    key: str
    label: str
    canonical_url: str | None = None
    title: str | None = None
    citation_count: int = 0
    evidence_ids: set[int] = field(default_factory=set)
    evidence_references: dict[int, _EvidenceReference] = field(default_factory=dict)
    brand_absent_evidence_ids: set[int] = field(default_factory=set)
    models: dict[str, _Breakdown] = field(default_factory=lambda: defaultdict(_Breakdown))
    questions: dict[int, _Breakdown] = field(default_factory=lambda: defaultdict(_Breakdown))


def normalize_source_url(value: Any) -> NormalizedSource | None:
    """Return a stable page/domain identity without claiming the page was crawled.

    Scheme and fragments do not split one page into multiple rows. A missing scheme
    is accepted for archived provider payloads, while non-HTTP schemes, credentials,
    missing hosts and malformed ports are ignored.
    """

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        host = parsed.hostname.rstrip(".").lower().encode("idna").decode("ascii")
        if host.startswith("www."):
            host = host[4:]
        if not host or "." not in host:
            return None
        port = parsed.port
    except (UnicodeError, ValueError):
        return None

    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    page_key = f"{netloc}{path}{f'?{query}' if query else ''}"
    canonical_url = urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))
    return NormalizedSource(domain=host, page_key=page_key, canonical_url=canonical_url)


def _captured_sort_key(evidence: GeoEvidence) -> tuple[datetime, int]:
    return evidence.captured_at, evidence.id


def _breakdowns(
    aggregate: _Aggregate,
    evidence_by_id: dict[int, GeoEvidence],
    questions: dict[int, GeoQuestionPlan],
) -> tuple[list[dict], list[dict]]:
    models = [
        {
            "key": key,
            "label": evidence_by_id[next(iter(value.evidence_ids))].model_label,
            "citation_count": value.citation_count,
            "answer_count": len(value.evidence_ids),
        }
        for key, value in aggregate.models.items()
    ]
    models.sort(key=lambda item: (-item["citation_count"], -item["answer_count"], item["label"]))
    question_rows = [
        {
            "id": question_id,
            "text": questions[question_id].question_text,
            "citation_count": value.citation_count,
            "answer_count": len(value.evidence_ids),
        }
        for question_id, value in aggregate.questions.items()
        if question_id in questions
    ]
    question_rows.sort(key=lambda item: (-item["citation_count"], -item["answer_count"], item["id"]))
    return models, question_rows


def _serialize_aggregate(
    aggregate: _Aggregate,
    evidence_by_id: dict[int, GeoEvidence],
    questions: dict[int, GeoQuestionPlan],
    evidence_limit: int,
) -> dict:
    evidence_ids = sorted(
        aggregate.evidence_ids,
        key=lambda evidence_id: _captured_sort_key(evidence_by_id[evidence_id]),
        reverse=True,
    )
    evidence_references = [
        aggregate.evidence_references[evidence_id]
        for evidence_id in evidence_ids
        if evidence_id in aggregate.evidence_references
    ]
    answer_count = len(evidence_ids)
    absent_count = len(aggregate.brand_absent_evidence_ids)
    models, question_rows = _breakdowns(aggregate, evidence_by_id, questions)
    return {
        "key": aggregate.key,
        "label": aggregate.label,
        "canonical_url": aggregate.canonical_url,
        "title": aggregate.title,
        "citation_count": aggregate.citation_count,
        "answer_count": answer_count,
        "model_count": len(aggregate.models),
        "brand_absent_answer_count": absent_count,
        "brand_absent_answer_ratio": round(absent_count / answer_count * 100, 1)
        if answer_count
        else 0.0,
        "evidence_ids": evidence_ids[:evidence_limit],
        "evidence_references": [
            {
                "evidence_id": reference.evidence_id,
                "source_url": reference.source_url,
                "source_title": reference.source_title,
            }
            for reference in evidence_references[:evidence_limit]
        ],
        "evidence_total": len(evidence_ids),
        "evidence_truncated": len(evidence_ids) > evidence_limit,
        "models": models,
        "questions": question_rows,
    }


def build_source_map(
    evidence_rows: list[GeoEvidence],
    question_rows: list[GeoQuestionPlan],
    *,
    limit: int,
    evidence_limit: int,
    excluded_non_real_answer_count: int = 0,
) -> dict:
    questions = {row.id: row for row in question_rows}
    evidence_by_id = {row.id: row for row in evidence_rows}
    domains: dict[str, _Aggregate] = {}
    pages: dict[str, _Aggregate] = {}
    ignored_source_count = 0
    duplicate_source_count = 0
    answers_with_sources: set[int] = set()
    total_citations = 0

    for evidence in evidence_rows:
        seen_pages: set[str] = set()
        for source in evidence.source_items or []:
            normalized = normalize_source_url(source.get("url") if isinstance(source, dict) else None)
            if normalized is None:
                ignored_source_count += 1
                continue
            if normalized.page_key in seen_pages:
                duplicate_source_count += 1
                continue
            seen_pages.add(normalized.page_key)
            answers_with_sources.add(evidence.id)
            total_citations += 1

            title = source.get("title") if isinstance(source, dict) else None
            source_title = title if isinstance(title, str) and title.strip() else None
            page = pages.setdefault(
                normalized.page_key,
                _Aggregate(
                    key=normalized.page_key,
                    label=normalized.canonical_url,
                    canonical_url=normalized.canonical_url,
                    title=source_title,
                ),
            )
            domain = domains.setdefault(
                normalized.domain,
                _Aggregate(key=normalized.domain, label=normalized.domain),
            )
            for aggregate in (page, domain):
                aggregate.citation_count += 1
                aggregate.evidence_ids.add(evidence.id)
                # A domain can occur more than once in one answer. Keep the
                # first concrete URL so an evidence link never becomes a vague,
                # domain-only jump with no matching source to inspect.
                aggregate.evidence_references.setdefault(
                    evidence.id,
                    _EvidenceReference(
                        evidence_id=evidence.id,
                        source_url=normalized.canonical_url,
                        source_title=source_title,
                    ),
                )
                if evidence.brand_status == "absent":
                    aggregate.brand_absent_evidence_ids.add(evidence.id)
                aggregate.models[evidence.model_key].citation_count += 1
                aggregate.models[evidence.model_key].evidence_ids.add(evidence.id)
                aggregate.questions[evidence.question_plan_id].citation_count += 1
                aggregate.questions[evidence.question_plan_id].evidence_ids.add(evidence.id)

    serialized_domains = [
        _serialize_aggregate(item, evidence_by_id, questions, evidence_limit)
        for item in domains.values()
    ]
    serialized_pages = [
        _serialize_aggregate(item, evidence_by_id, questions, evidence_limit)
        for item in pages.values()
    ]
    def rank_key(item: dict) -> tuple[int, int, str]:
        return (-item["citation_count"], -item["answer_count"], item["label"])

    serialized_domains.sort(key=rank_key)
    serialized_pages.sort(key=rank_key)
    opportunities = [
        {
            **item,
            "reason": (
                f"该域名出现在 {item['brand_absent_answer_count']} 条未出现品牌的回答引用中；"
                "这里只代表引用关系，尚未核验网页正文是否提及品牌。"
            ),
        }
        for item in sorted(
            (item for item in serialized_domains if item["brand_absent_answer_count"] > 0),
            key=lambda item: (
                -item["brand_absent_answer_count"],
                -item["citation_count"],
                -item["brand_absent_answer_ratio"],
                item["label"],
            ),
        )[:limit]
    ]
    absent_answers_with_sources = {
        evidence_id
        for evidence_id in answers_with_sources
        if evidence_by_id[evidence_id].brand_status == "absent"
    }
    return {
        "summary": {
            "answer_count": len(evidence_rows),
            "answers_with_sources": len(answers_with_sources),
            "citation_count": total_citations,
            "unique_domain_count": len(domains),
            "unique_page_count": len(pages),
            "brand_absent_answer_count": len(absent_answers_with_sources),
            "brand_absent_answer_ratio": round(
                len(absent_answers_with_sources) / len(answers_with_sources) * 100, 1
            )
            if answers_with_sources
            else 0.0,
            "ignored_source_count": ignored_source_count,
            "duplicate_source_count": duplicate_source_count,
            "excluded_non_real_answer_count": excluded_non_real_answer_count,
        },
        "domains": serialized_domains[:limit],
        "pages": serialized_pages[:limit],
        "opportunities": opportunities,
    }
