"""Capture evidence-bounded visual assets from a workspace's official website."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ipaddress
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from PIL import Image, ImageStat

from app.services.article_media import MAX_ARTICLE_VISUALS
from app.v1.website_audit import (
    Resolver,
    WebsiteAuditTargetError,
    _default_resolver,
    _resolve_public_target,
)


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True)
class CapturedVisual:
    path: Path
    source_url: str
    alt_text: str
    purpose: str
    recommended_platforms: list[str]
    sha256: str
    size_bytes: int
    capture_engine: str


@dataclass(frozen=True)
class CaptureOutcome:
    status: str
    items: list[CapturedVisual]
    reason: str | None = None


Runner = Callable[[list[str], int], CommandResult]


def run_command(arguments: list[str], timeout_seconds: int) -> CommandResult:
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
        return CommandResult(completed.stdout, completed.stderr, completed.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult("", str(exc), 124)


def _canonical_official_url(candidate: str, official_website: str) -> str | None:
    """Accept only public HTTP(S) URLs on the exact configured official host."""
    official = urlsplit(official_website.strip())
    value = urlsplit(candidate.strip())
    if official.scheme not in {"http", "https"} or value.scheme not in {"http", "https"}:
        return None
    if official.scheme.lower() != value.scheme.lower():
        return None
    if not official.hostname or not value.hostname:
        return None
    if official.username or official.password or value.username or value.password:
        return None
    if official.hostname.lower().rstrip(".") != value.hostname.lower().rstrip("."):
        return None
    try:
        official_port = official.port or (443 if official.scheme == "https" else 80)
        value_port = value.port or (443 if value.scheme == "https" else 80)
    except ValueError:
        return None
    if official_port != value_port:
        return None
    path = value.path or "/"
    normalized_host = value.hostname.lower().rstrip(".")
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    default_port = 443 if value.scheme.lower() == "https" else 80
    authority = (
        normalized_host if value_port == default_port else f"{normalized_host}:{value_port}"
    )
    return urlunsplit((value.scheme.lower(), authority, path, value.query, ""))


def _valid_png(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with Image.open(path) as image:
            if image.format != "PNG" or image.width < 800 or image.height < 500:
                return False
            sample = image.convert("RGB")
            sample.thumbnail((160, 100))
            stat = ImageStat.Stat(sample)
            channel_spread = max(high - low for low, high in stat.extrema)
            channel_variation = max(stat.stddev)
            return channel_spread >= 20 and channel_variation >= 5
    except (OSError, ValueError):
        return False


def captured_visual_purpose(value: str) -> str:
    """Turn an Agent's pre-capture proposal into truthful post-capture copy."""
    purpose = value.strip()
    sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])", purpose) if item.strip()]
    forward_looking = re.compile(r"(未执行截图|未完成截图|尚未截图|待截图|建议截取|建议截图)")
    factual = [sentence for sentence in sentences if not forward_looking.search(sentence)]
    result = "".join(factual).strip()
    result = re.sub(r"^候选截图", "该官网截图", result)
    result = re.sub(r"^截图候选", "该官网截图", result)
    return result[:500] or "已从官网真实采集，供内容审核与配图选择。"


class OfficialSiteCapture:
    """Capture official pages in an isolated browser pinned to a validated public IP."""

    def __init__(
        self,
        runner: Runner = run_command,
        resolver: Resolver = _default_resolver,
    ) -> None:
        self.runner = runner
        self.resolver = resolver

    def capture(
        self,
        *,
        run_id: int,
        official_website: str | None,
        candidates: list[dict],
        output_directory: Path,
    ) -> CaptureOutcome:
        if not official_website or not candidates:
            return CaptureOutcome(status="not_requested", items=[])
        accepted: list[dict] = []
        seen: set[str] = set()
        unsafe_target_seen = False
        for candidate in candidates:
            source_url = _canonical_official_url(
                str(candidate.get("source_url") or ""), official_website
            )
            if not source_url or source_url in seen:
                continue
            try:
                public_target = _resolve_public_target(source_url, resolver=self.resolver)
            except WebsiteAuditTargetError:
                unsafe_target_seen = True
                continue
            seen.add(source_url)
            approved_address = next(
                (
                    address
                    for address in public_target.addresses
                    if ipaddress.ip_address(address).version == 4
                ),
                public_target.addresses[0],
            )
            accepted.append(
                {
                    "source_url": source_url,
                    "approved_host": public_target.host,
                    "approved_address": approved_address,
                    "approved_port": public_target.port,
                    "alt_text": str(candidate.get("alt_text") or "春秋元泉官网页面截图").strip()[:300],
                    "purpose": str(candidate.get("purpose") or "内容审核参考").strip()[:500],
                    "recommended_platforms": list(
                        dict.fromkeys(
                            str(item)
                            for item in (candidate.get("recommended_platforms") or [])
                            if str(item)
                        )
                    )[:4],
                }
            )
            if len(accepted) == MAX_ARTICLE_VISUALS:
                break
        if not accepted:
            return CaptureOutcome(
                status="rejected",
                items=[],
                reason=(
                    "unsafe_official_target"
                    if unsafe_target_seen
                    else "no_official_domain_candidate"
                ),
            )
        output_directory.mkdir(parents=True, exist_ok=True)
        captured: list[CapturedVisual] = []
        failure_reason: str | None = None
        for candidate in accepted:
            with TemporaryDirectory(prefix="geo-official-capture-") as temporary_directory:
                temporary_target = Path(temporary_directory) / "official-page.png"
                playwright_capture = self.runner(
                    [
                        sys.executable,
                        "-m",
                        "app.services.secure_official_browser",
                        "--url",
                        candidate["source_url"],
                        "--approved-host",
                        candidate["approved_host"],
                        "--approved-address",
                        candidate["approved_address"],
                        "--approved-port",
                        str(candidate["approved_port"]),
                        "--output",
                        str(temporary_target),
                    ],
                    90,
                )
                if playwright_capture.returncode == 0 and _valid_png(temporary_target):
                    target = output_directory / f"official-page-{uuid4().hex[:10]}.png"
                    temporary_target.replace(target)
                    payload = target.read_bytes()
                    captured.append(
                        CapturedVisual(
                            path=target,
                            source_url=candidate["source_url"],
                            alt_text=candidate["alt_text"],
                            purpose=captured_visual_purpose(candidate["purpose"]),
                            recommended_platforms=candidate["recommended_platforms"],
                            sha256=sha256(payload).hexdigest(),
                            size_bytes=len(payload),
                            capture_engine="playwright_chrome",
                        )
                    )
                    continue
                failure_reason = (
                    "official_page_visual_empty"
                    if playwright_capture.returncode == 0
                    else "isolated_browser_capture_failed"
                )
        if captured:
            return CaptureOutcome(
                status="captured" if len(captured) == len(accepted) else "partial",
                items=captured,
                reason=failure_reason,
            )
        return CaptureOutcome(
            status="unavailable",
            items=[],
            reason=failure_reason or "isolated_browser_capture_failed",
        )
