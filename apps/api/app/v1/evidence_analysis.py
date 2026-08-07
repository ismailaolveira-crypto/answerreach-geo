"""Deterministic first-pass analysis shared by every collection adapter."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata
from urllib.parse import urlsplit


@dataclass(frozen=True)
class BrandTextMatch:
    alias: str
    start: int
    end: int


@lru_cache(maxsize=512)
def _alias_pattern(alias: str) -> re.Pattern[str]:
    """Compile each stable brand alias once per API process."""
    normalized = unicodedata.normalize("NFKC", alias).strip()
    compact = re.sub(r"\s+", "", normalized)
    body = r"\s*".join(re.escape(character) for character in compact)
    left = r"(?<![A-Za-z0-9_])" if compact and compact[0].isascii() and compact[0].isalnum() else ""
    right = r"(?![A-Za-z0-9_])" if compact and compact[-1].isascii() and compact[-1].isalnum() else ""
    return re.compile(f"{left}{body}{right}", re.IGNORECASE)


@lru_cache(maxsize=4096)
def _find_brand_mentions_cached(
    answer: str, unique_aliases: tuple[str, ...]
) -> tuple[BrandTextMatch, ...]:
    normalized_answer = unicodedata.normalize("NFKC", answer)
    candidates: list[BrandTextMatch] = []
    for alias in unique_aliases:
        candidates.extend(
            BrandTextMatch(alias=alias, start=match.start(), end=match.end())
            for match in _alias_pattern(alias).finditer(normalized_answer)
        )
    candidates.sort(key=lambda item: (item.start, -(item.end - item.start), item.alias.casefold()))
    matches: list[BrandTextMatch] = []
    for candidate in candidates:
        if any(candidate.start < item.end and item.start < candidate.end for item in matches):
            continue
        matches.append(candidate)
    return tuple(matches)


def find_brand_mentions(answer: str, aliases: list[str]) -> list[BrandTextMatch]:
    """Find deduplicated aliases with NFKC, whitespace and English-boundary handling.

    Evidence answers are immutable after archival, while analytics pages inspect
    the same answer and brand aliases repeatedly. Cache that deterministic match
    result so returning to a report does not rescan every long answer again.
    """

    unique_aliases = tuple(sorted(
        {alias.strip() for alias in aliases if alias and alias.strip()},
        key=lambda item: (-len(re.sub(r"\s+", "", item)), item.casefold()),
    ))
    return list(_find_brand_mentions_cached(answer or "", unique_aliases))


def analyze_brand_status(
    answer: str,
    references: list[dict],
    brand_name: str,
    aliases: list[str],
    owned_domains: list[str] | None = None,
) -> tuple[str, int | None]:
    """Classify one answer without an LLM so the result is reproducible.

    This is intentionally conservative: a source only counts as a brand citation
    when its title/URL names the brand or its host belongs to a configured brand
    domain.  General web sources still remain attached to the evidence record.
    """

    names = [name.strip() for name in [brand_name, *aliases] if name and name.strip()]
    normalized_answer = unicodedata.normalize("NFKC", answer)
    lowered = normalized_answer.lower()
    matches = find_brand_mentions(answer, names)
    if not matches:
        return "absent", None
    matched = matches[0]

    normalized_domains = {
        domain.lower().removeprefix("www.").strip(".")
        for domain in (owned_domains or [])
        if domain
    }

    def is_brand_source(item: dict) -> bool:
        title_and_url = f"{item.get('title', '')} {item.get('url', '')}"
        if find_brand_mentions(title_and_url, names):
            return True
        raw_url = str(item.get("url") or "")
        host = (urlsplit(raw_url).hostname or "").lower().removeprefix("www.")
        return any(host == domain or host.endswith(f".{domain}") for domain in normalized_domains)

    cited = any(is_brand_source(item) for item in references)
    lines = [unicodedata.normalize("NFKC", line.strip()) for line in answer.splitlines() if line.strip()]
    position = None
    for fallback_index, line in enumerate(lines, 1):
        if not find_brand_mentions(line, [matched.alias]):
            continue
        list_match = re.match(r"^(?:#{1,6}\s*)?(\d+)[.、)]\s*", line)
        if list_match:
            position = int(list_match.group(1))
            break
        if re.match(r"^(?:#{1,6}\s*)?[-*•]\s*", line):
            position = fallback_index
            break

    # Negation must win over recommendation wording. A bare substring check
    # previously classified “不推荐春秋元泉” as recommended, which could
    # corrupt both the decision map and the optimization queue.
    negative_patterns = (
        "不推荐", "不建议", "不是首选", "非首选", "未推荐", "没有推荐",
        "不列入候选", "未列入候选", "未进入候选", "没有提及", "未提及", "不引用",
    )
    recommendation_words = ("推荐", "首选", "优先", "建议选择", "值得考虑")
    mention_index = matched.start
    window = lowered[max(0, mention_index - 60):matched.end + 60]
    if any(pattern in window for pattern in negative_patterns):
        return "negative", position
    if cited:
        return "cited", position
    if any(word in window for word in recommendation_words):
        return "recommended", position
    if position is not None and position <= 5:
        return "shortlisted", position
    return "mentioned", None
