"""Policy and persistence helpers for evidence-bounded article images."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from PIL import Image


FACTUAL_TERMS = re.compile(
    r"(logo|标志|真人|人物|客户|产品界面|截图|仪表盘|证书|认证|新闻|事件|统计|数据|报告|门店|工厂)",
    re.IGNORECASE,
)

# This is a safety and cost ceiling, not a target. The drafting model may
# return any number from zero up to this limit after reading the article.
MAX_ARTICLE_VISUALS = 6


@dataclass(frozen=True)
class ImageInspection:
    sha256: str
    size_bytes: int
    media_type: str
    width: int
    height: int


def choose_media_strategy(candidate: dict) -> tuple[str, str]:
    """Return the enforced strategy and an auditable reason.

    The model may recommend a path, but the host owns the final policy.  Any
    factual subject is forced onto the sourced-web path so image generation
    cannot invent product evidence, people, logos, certifications or metrics.
    """

    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("purpose", "alt_text", "caption", "generation_prompt")
    )
    factual = bool(candidate.get("factual_subject")) or bool(FACTUAL_TERMS.search(text))
    if factual:
        return "web_search", "涉及真实主体或事实证据，只允许使用可追溯网络原图"
    requested = str(candidate.get("strategy") or "").strip()
    if requested == "web_search" and candidate.get("source_url"):
        return "web_search", str(candidate.get("decision_reason") or "需要保留公开来源")[:300]
    return "generate", str(candidate.get("decision_reason") or "概念解释更适合定制生成图")[:300]


def generation_prompt(candidate: dict, *, article_title: str) -> str:
    subject = str(candidate.get("generation_prompt") or candidate.get("purpose") or "").strip()
    caption = str(candidate.get("caption") or "").strip()
    return f"""Use case: infographic-diagram
Asset type: editorial image for a Chinese enterprise GEO article
Primary request: {subject}
Article context: {article_title}
Caption intent: {caption}
Style: clean editorial illustration or clear explanatory diagram, Apple-inspired restraint, white and soft blue palette, strong hierarchy, 16:9 landscape
Constraints: no logo, no trademark imitation, no real person, no customer claim, no certification, no measured data, no fake product screenshot, no watermark, no unexplained text
Avoid: decorative stock-photo look, dark cyberpunk, dense tiny labels, unsupported factual claims
"""


def inspect_image(path: Path) -> ImageInspection:
    payload = path.read_bytes()
    if not payload:
        raise ValueError("image artifact is empty")
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        media_type = Image.MIME.get(image.format or "", "")
    if media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("unsupported image media type")
    if width < 800 or height < 450:
        raise ValueError("article image is below the 800x450 quality floor")
    return ImageInspection(
        sha256=sha256(payload).hexdigest(),
        size_bytes=len(payload),
        media_type=media_type,
        width=width,
        height=height,
    )


def manifest_entry(
    candidate: dict,
    *,
    strategy: str,
    decision_reason: str,
    artifact_id: int,
    inspection: ImageInspection,
    provider: str,
    model: str | None = None,
    revised_prompt: str | None = None,
) -> dict:
    return {
        "status": "ready",
        "review_status": "pending",
        "strategy": strategy,
        "decision_reason": decision_reason,
        "artifact_id": artifact_id,
        "artifact_kind": "generated_article_image",
        "source_url": candidate.get("source_url"),
        "license_name": candidate.get("license_name"),
        "alt_text": str(candidate.get("alt_text") or "文章配图").strip()[:300],
        "caption": str(candidate.get("caption") or "").strip()[:500],
        "placement": str(candidate.get("placement") or "after_intro"),
        "purpose": str(candidate.get("purpose") or "正文解释配图").strip()[:500],
        "recommended_platforms": list(candidate.get("recommended_platforms") or [])[:8],
        "sha256": inspection.sha256,
        "size_bytes": inspection.size_bytes,
        "media_type": inspection.media_type,
        "width": inspection.width,
        "height": inspection.height,
        "provider": provider,
        "model": model,
        "generation_prompt": revised_prompt or candidate.get("generation_prompt"),
        "quality_gate": "passed",
    }
