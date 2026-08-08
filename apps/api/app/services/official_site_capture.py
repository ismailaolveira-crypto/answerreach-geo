"""Capture evidence-bounded visual assets from a workspace's official website."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from PIL import Image, ImageStat


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


def _json_object(raw: str) -> dict | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


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
    if not official.hostname or not value.hostname:
        return None
    if value.username or value.password:
        return None
    if official.hostname.lower().rstrip(".") != value.hostname.lower().rstrip("."):
        return None
    official_port = official.port or (443 if official.scheme == "https" else 80)
    value_port = value.port or (443 if value.scheme == "https" else 80)
    if official_port != value_port:
        return None
    path = value.path or "/"
    return urlunsplit((value.scheme.lower(), value.netloc.lower(), path, value.query, ""))


def _connected_profile(runner: Runner) -> str | None:
    result = runner(["opencli", "profile", "list"], 15)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if "connected" not in line.lower() or "not connected" in line.lower():
            continue
        match = re.match(
            r"^\s*(?:•\s*)?([A-Za-z0-9_-]+)\s+([^\s—]+)\s+[—-]\s+connected\b",
            line,
        )
        if match:
            return match.group(2)
    return None


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


class OfficialSiteCapture:
    """Capture public official pages in isolated Chrome, with OpenCLI as fallback."""

    def __init__(self, runner: Runner = run_command) -> None:
        self.runner = runner

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
        for candidate in candidates:
            source_url = _canonical_official_url(
                str(candidate.get("source_url") or ""), official_website
            )
            if not source_url or source_url in seen:
                continue
            seen.add(source_url)
            accepted.append(
                {
                    "source_url": source_url,
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
            if len(accepted) == 2:
                break
        if not accepted:
            return CaptureOutcome(status="rejected", items=[], reason="no_official_domain_candidate")
        output_directory.mkdir(parents=True, exist_ok=True)
        captured: list[CapturedVisual] = []
        failure_reason: str | None = None
        remaining: list[dict] = []
        for candidate in accepted:
            with TemporaryDirectory(prefix="geo-official-capture-") as temporary_directory:
                temporary_target = Path(temporary_directory) / "official-page.png"
                playwright_capture = self.runner(
                    [
                        "playwright",
                        "screenshot",
                        "--channel",
                        "chrome",
                        "--wait-for-timeout",
                        "5000",
                        "--viewport-size",
                        "1440,900",
                        "--timeout",
                        "60000",
                        candidate["source_url"],
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
                            purpose=candidate["purpose"],
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
                remaining.append(candidate)
        if not remaining:
            return CaptureOutcome(status="captured", items=captured)

        profile = _connected_profile(self.runner)
        if not profile:
            return CaptureOutcome(
                status="partial" if captured else "unavailable",
                items=captured,
                reason=failure_reason or "browser_bridge_not_connected",
            )

        session = f"geo-material-{run_id}"
        try:
            for index, candidate in enumerate(remaining, start=1):
                target = output_directory / f"official-page-{index}-{uuid4().hex[:10]}.png"
                opened = self.runner(
                    [
                        "opencli",
                        "--profile",
                        profile,
                        "browser",
                        session,
                        "open",
                        candidate["source_url"],
                    ],
                    45,
                )
                if opened.returncode != 0:
                    failure_reason = "official_page_open_failed"
                    continue
                page_id = str((_json_object(opened.stdout) or {}).get("page") or "")
                if not page_id:
                    failure_reason = "official_page_identity_missing"
                    continue
                waited = self.runner(
                    [
                        "opencli",
                        "--profile",
                        profile,
                        "browser",
                        session,
                        "wait",
                        "--tab",
                        page_id,
                        "time",
                        "3",
                    ],
                    10,
                )
                inspected = self.runner(
                    [
                        "opencli",
                        "--profile",
                        profile,
                        "browser",
                        session,
                        "eval",
                        "--tab",
                        page_id,
                        "({url:location.href,title:document.title,textLength:(document.body.innerText||'').trim().length,htmlLength:document.documentElement.outerHTML.length,imageCount:document.images.length,canvasCount:document.querySelectorAll('canvas').length})",
                    ],
                    20,
                )
                page_state = _json_object(inspected.stdout) if inspected.returncode == 0 else None
                final_url = _canonical_official_url(
                    str((page_state or {}).get("url") or ""), official_website
                )
                has_visible_material = bool(
                    int((page_state or {}).get("textLength") or 0) >= 40
                    or int((page_state or {}).get("imageCount") or 0) > 0
                    or int((page_state or {}).get("canvasCount") or 0) > 0
                )
                if (
                    not final_url
                    or int((page_state or {}).get("htmlLength") or 0) < 200
                    or not has_visible_material
                ):
                    failure_reason = (
                        "official_page_render_timeout"
                        if waited.returncode != 0
                        else "official_page_visual_empty"
                    )
                    continue
                screenshot = self.runner(
                    [
                        "opencli",
                        "--profile",
                        profile,
                        "browser",
                        session,
                        "screenshot",
                        "--tab",
                        page_id,
                        str(target),
                        "--width",
                        "1440",
                        "--height",
                        "900",
                    ],
                    60,
                )
                if screenshot.returncode != 0:
                    failure_reason = "official_page_screenshot_command_failed"
                    continue
                if not target.is_file():
                    failure_reason = "official_page_screenshot_file_missing"
                    continue
                if target.stat().st_size == 0:
                    failure_reason = "official_page_screenshot_empty"
                    continue
                if not _valid_png(target):
                    failure_reason = "official_page_visual_empty"
                    continue
                payload = target.read_bytes()
                captured.append(
                    CapturedVisual(
                        path=target,
                        source_url=candidate["source_url"],
                        alt_text=candidate["alt_text"],
                        purpose=candidate["purpose"],
                        recommended_platforms=candidate["recommended_platforms"],
                        sha256=sha256(payload).hexdigest(),
                        size_bytes=len(payload),
                        capture_engine="opencli_browser_bridge",
                    )
                )
        finally:
            self.runner(
                ["opencli", "--profile", profile, "browser", session, "close"],
                15,
            )
        if captured:
            return CaptureOutcome(
                status="captured" if len(captured) == len(accepted) else "partial",
                items=captured,
                reason=failure_reason,
            )
        return CaptureOutcome(status="failed", items=[], reason=failure_reason or "capture_failed")
