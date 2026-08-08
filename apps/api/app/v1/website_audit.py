from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
from time import perf_counter
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


AUDIT_VERSION = "website-citation-audit.v1"
MAX_HOME_BYTES = 512 * 1024
MAX_DISCOVERY_BYTES = 128 * 1024
USER_AGENT = "ChunqiuYuanquan-GEO-Audit/1.0 (+website citation readiness)"
PUBLICATION_VERIFY_MAX_BYTES = 128 * 1024
BRAND_FACT_VERIFY_MAX_BYTES = 512 * 1024


class WebsiteAuditTargetError(ValueError):
    """Raised when a configured workspace URL is unsafe or unsupported."""


class PublicationVerificationError(ValueError):
    """Raised when a claimed public page cannot be verified as readable HTML."""


class BrandFactSourceVerificationError(ValueError):
    """Raised when a public page does not prove the submitted brand statement."""


Resolver = Callable[[str, int], list[str]]


@dataclass
class _ParsedPage:
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    canonical_url: str = ""
    body_text_parts: list[str] = field(default_factory=list)
    headings: dict[str, list[str]] = field(default_factory=lambda: {"h1": [], "h2": []})
    links: list[str] = field(default_factory=list)
    script_sources: list[str] = field(default_factory=list)
    structured_types: list[str] = field(default_factory=list)
    _in_title: bool = False
    _in_body: bool = False
    _skip_depth: int = 0
    _heading: str | None = None
    _heading_parts: list[str] = field(default_factory=list)
    _json_ld_depth: int = 0
    _json_ld_parts: list[str] = field(default_factory=list)

    @property
    def body_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.body_text_parts)).strip()


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page = _ParsedPage()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        values = {key.lower(): (value or "") for key, value in attrs}
        if name == "title":
            self.page._in_title = True
        elif name == "body":
            self.page._in_body = True
        elif name in {"script", "style", "noscript", "template"}:
            if name == "script" and values.get("type", "").lower() == "application/ld+json":
                self.page._json_ld_depth += 1
            else:
                self.page._skip_depth += 1
            if name == "script" and values.get("src"):
                self.page.script_sources.append(values["src"].strip())
        elif name == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            content = values.get("content", "").strip()
            if key in {"description", "og:description"} and not self.page.meta_description:
                self.page.meta_description = content
            if key in {"robots", "googlebot"} and not self.page.meta_robots:
                self.page.meta_robots = content
        elif name == "link":
            rel = {part.lower() for part in values.get("rel", "").split()}
            if "canonical" in rel and values.get("href"):
                self.page.canonical_url = values["href"].strip()
        elif name == "a" and values.get("href"):
            self.page.links.append(values["href"].strip())

        if name in self.page.headings:
            self.page._heading = name
            self.page._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self.page._in_title = False
        elif name == "body":
            self.page._in_body = False
        elif name == "script" and self.page._json_ld_depth:
            self.page._json_ld_depth -= 1
            if not self.page._json_ld_depth:
                self._record_json_ld("".join(self.page._json_ld_parts))
                self.page._json_ld_parts = []
        elif name in {"script", "style", "noscript", "template"} and self.page._skip_depth:
            self.page._skip_depth -= 1

        if self.page._heading == name:
            text = re.sub(r"\s+", " ", " ".join(self.page._heading_parts)).strip()
            if text:
                self.page.headings[name].append(text)
            self.page._heading = None
            self.page._heading_parts = []

    def handle_data(self, data: str) -> None:
        if self.page._json_ld_depth:
            self.page._json_ld_parts.append(data)
            return
        if self.page._skip_depth:
            return
        value = data.strip()
        if not value:
            return
        if self.page._in_title:
            self.page.title = f"{self.page.title} {value}".strip()
        if self.page._heading:
            self.page._heading_parts.append(value)
        if self.page._in_body:
            self.page.body_text_parts.append(value)

    def _record_json_ld(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                item_type = value.get("@type")
                if isinstance(item_type, str):
                    self.page.structured_types.append(item_type)
                elif isinstance(item_type, list):
                    self.page.structured_types.extend(
                        str(item) for item in item_type if isinstance(item, str)
                    )
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)


def _default_resolver(host: str, port: int) -> list[str]:
    return sorted({item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def _validate_public_url(url: str, *, resolver: Resolver) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise WebsiteAuditTargetError("website_url_requires_http_or_https")
    if parsed.username or parsed.password:
        raise WebsiteAuditTargetError("website_url_credentials_not_allowed")
    host = parsed.hostname
    if not host:
        raise WebsiteAuditTargetError("website_url_host_missing")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise WebsiteAuditTargetError("website_url_port_invalid") from exc
    if port not in {80, 443}:
        raise WebsiteAuditTargetError("website_url_port_not_allowed")
    try:
        addresses = resolver(host, port)
    except OSError as exc:
        raise WebsiteAuditTargetError("website_url_dns_failed") from exc
    if not addresses:
        raise WebsiteAuditTargetError("website_url_dns_empty")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise WebsiteAuditTargetError("website_url_dns_invalid") from exc
        if not ip.is_global:
            raise WebsiteAuditTargetError("website_url_private_network_blocked")
    normalized_path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, normalized_path, parsed.query, ""))


def _filtered_headers(headers: httpx.Headers) -> dict[str, str]:
    allowed = {
        "cache-control",
        "content-language",
        "content-length",
        "content-type",
        "etag",
        "last-modified",
        "server",
        "x-robots-tag",
    }
    return {key.lower(): value for key, value in headers.items() if key.lower() in allowed}


def _decode(data: bytes, response: httpx.Response) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _fetch(
    client: httpx.Client,
    url: str,
    *,
    resolver: Resolver,
    max_bytes: int,
    max_redirects: int = 5,
) -> dict[str, Any]:
    current = url
    redirects: list[dict[str, Any]] = []
    for _ in range(max_redirects + 1):
        current = _validate_public_url(current, resolver=resolver)
        with client.stream("GET", current, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    break
                target = urljoin(current, location)
                redirects.append({"status_code": response.status_code, "url": current, "to": target})
                current = target
                continue
            chunks: list[bytes] = []
            size = 0
            truncated = False
            for chunk in response.iter_bytes():
                remaining = max_bytes - size
                if remaining <= 0:
                    truncated = True
                    break
                chunks.append(chunk[:remaining])
                size += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    truncated = True
                    break
            body_bytes = b"".join(chunks)
            return {
                "url": current,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "headers": _filtered_headers(response.headers),
                "body": _decode(body_bytes, response),
                "sha256": sha256(body_bytes).hexdigest(),
                "size_bytes": len(body_bytes),
                "truncated": truncated,
                "redirects": redirects,
            }
    raise httpx.TooManyRedirects("Website audit exceeded redirect limit", request=None)


def verify_publication_page(
    url: str,
    *,
    resolver: Resolver = _default_resolver,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch a public page safely and return a compact, persisted proof snapshot."""
    owned_client = client is None
    active_client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=httpx.Timeout(12.0, connect=8.0),
        follow_redirects=False,
    )
    try:
        document = _fetch(
            active_client,
            url,
            resolver=resolver,
            max_bytes=PUBLICATION_VERIFY_MAX_BYTES,
        )
    except WebsiteAuditTargetError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise PublicationVerificationError("public_page_request_failed") from exc
    finally:
        if owned_client:
            active_client.close()
    status_code = int(document.get("status_code") or 0)
    if status_code < 200 or status_code >= 400:
        raise PublicationVerificationError(f"public_page_http_{status_code or 'unknown'}")
    content_type = str(document.get("content_type") or "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise PublicationVerificationError("public_page_not_html")
    if int(document.get("size_bytes") or 0) < 64:
        raise PublicationVerificationError("public_page_body_too_small")
    return {
        "status": "publicly_verified",
        "verified_url": document["url"],
        "status_code": status_code,
        "content_type": content_type,
        "sha256": document["sha256"],
        "size_bytes": document["size_bytes"],
        "truncated": bool(document.get("truncated")),
        "redirect_count": len(document.get("redirects") or []),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_brand_fact_source(
    url: str,
    statement: str,
    *,
    resolver: Resolver = _default_resolver,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Verify that public server-rendered HTML contains the submitted statement."""

    owned_client = client is None
    active_client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=httpx.Timeout(12.0, connect=8.0),
        follow_redirects=False,
    )
    try:
        document = _fetch(
            active_client,
            url,
            resolver=resolver,
            max_bytes=BRAND_FACT_VERIFY_MAX_BYTES,
        )
    except WebsiteAuditTargetError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise BrandFactSourceVerificationError("brand_fact_source_request_failed") from exc
    finally:
        if owned_client:
            active_client.close()

    status_code = int(document.get("status_code") or 0)
    if status_code < 200 or status_code >= 300:
        raise BrandFactSourceVerificationError(
            f"brand_fact_source_http_{status_code or 'unknown'}"
        )
    content_type = str(document.get("content_type") or "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise BrandFactSourceVerificationError("brand_fact_source_not_html")

    parser = _PageParser()
    parser.feed(str(document.get("body") or ""))
    visible_text = re.sub(r"\s+", "", parser.page.body_text)
    normalized_statement = re.sub(r"\s+", "", statement.strip())
    if not normalized_statement or normalized_statement not in visible_text:
        raise BrandFactSourceVerificationError("brand_fact_statement_not_found")

    return {
        "status": "source_and_statement_verified",
        "verified_url": document["url"],
        "status_code": status_code,
        "content_type": content_type,
        "source_sha256": document["sha256"],
        "statement_sha256": sha256(statement.strip().encode("utf-8")).hexdigest(),
        "size_bytes": document["size_bytes"],
        "truncated": bool(document.get("truncated")),
        "redirect_count": len(document.get("redirects") or []),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def _check(label: str, passed: bool, detail: str, weight: int) -> dict[str, Any]:
    return {
        "label": label,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "detail": detail,
        "weight": weight,
    }


def _artifact(document: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "url": document["url"],
        "status_code": document["status_code"],
        "content_type": document["content_type"],
        "sha256": document["sha256"],
        "size_bytes": document["size_bytes"],
        "truncated": document["truncated"],
    }


def _blocked_result(url: str, started: float, code: str, detail: str) -> dict[str, Any]:
    return {
        "requested_url": url,
        "final_url": None,
        "status": "blocked",
        "status_code": None,
        "content_type": None,
        "title": None,
        "meta_description": None,
        "canonical_url": None,
        "score": 0.0,
        "checks": {
            "accessible": _check("首页可访问", False, detail, 15),
        },
        "findings": [
            {
                "code": code,
                "severity": "high",
                "title": "官网检查未完成",
                "detail": detail,
                "recommendation": "确认官网地址和公网访问状态后重新检查。",
            }
        ],
        "response_headers": {},
        "raw_html": None,
        "raw_html_sha256": None,
        "raw_html_size": 0,
        "discovery_documents": {},
        "artifact_manifest": [],
        "response_ms": round((perf_counter() - started) * 1000),
        "checked_at": datetime.now(timezone.utc),
        "audit_version": AUDIT_VERSION,
    }


def audit_website(
    url: str,
    *,
    brand_name: str,
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Capture and score one configured public website without browser rendering.

    The result intentionally distinguishes HTTP availability from server-visible
    content. JavaScript-rendered claims are never inferred from script bundles.
    """

    started = perf_counter()
    resolve = resolver or _default_resolver
    normalized = _validate_public_url(url, resolver=resolve)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            transport=transport,
            trust_env=False,
        ) as client:
            home = _fetch(client, normalized, resolver=resolve, max_bytes=MAX_HOME_BYTES)
            final = urlsplit(home["url"])
            origin = urlunsplit((final.scheme, final.netloc, "", "", ""))
            discovery: dict[str, dict[str, Any]] = {}
            for kind, path in (("robots", "/robots.txt"), ("sitemap", "/sitemap.xml")):
                try:
                    discovery[kind] = _fetch(
                        client,
                        f"{origin}{path}",
                        resolver=resolve,
                        max_bytes=MAX_DISCOVERY_BYTES,
                    )
                except (httpx.HTTPError, WebsiteAuditTargetError) as exc:
                    discovery[kind] = {
                        "url": f"{origin}{path}",
                        "status_code": None,
                        "content_type": "",
                        "headers": {},
                        "body": "",
                        "sha256": None,
                        "size_bytes": 0,
                        "truncated": False,
                        "redirects": [],
                        "error": type(exc).__name__,
                    }
    except WebsiteAuditTargetError:
        raise
    except httpx.HTTPError as exc:
        return _blocked_result(
            normalized,
            started,
            "website_request_failed",
            f"公网请求失败：{type(exc).__name__}",
        )

    html = home["body"]
    parser = _PageParser()
    try:
        parser.feed(html)
    except (TypeError, ValueError):
        pass
    page = parser.page
    content_type = str(home["content_type"]).lower()
    accessible = 200 <= int(home["status_code"]) < 300 and (
        "html" in content_type or html.lstrip().lower().startswith(("<!doctype html", "<html"))
    )
    noindex = "noindex" in page.meta_robots.lower() or "noindex" in str(
        home["headers"].get("x-robots-tag", "")
    ).lower()
    visible_length = len(page.body_text)
    server_visible = visible_length >= 120
    client_rendering_required = bool(page.script_sources and visible_length < 120)
    headings_present = bool(page.headings["h1"] or page.headings["h2"])
    structured_types = sorted(set(page.structured_types))
    structured_present = bool(structured_types)
    brand_visible = bool(brand_name.strip() and brand_name.strip().lower() in page.body_text.lower())

    final_host = (final.hostname or "").lower()
    external_links = []
    for href in page.links:
        absolute = urljoin(home["url"], href)
        parsed = urlsplit(absolute)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            host = parsed.hostname.lower()
            if host != final_host and not host.endswith(f".{final_host}"):
                external_links.append(absolute)
    external_links = list(dict.fromkeys(external_links))

    robots = discovery["robots"]
    sitemap = discovery["sitemap"]
    robots_ok = robots["status_code"] == 200 and bool(
        re.search(
            r"^\s*(?:user-agent|allow|disallow|sitemap)\s*:",
            robots["body"],
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )
    sitemap_body = sitemap["body"].lstrip().lower()
    sitemap_ok = sitemap["status_code"] == 200 and (
        "<urlset" in sitemap_body or "<sitemapindex" in sitemap_body
    )
    canonical = urljoin(home["url"], page.canonical_url) if page.canonical_url else ""

    checks = {
        "accessible": _check(
            "首页可访问",
            accessible,
            f"HTTP {home['status_code']} · {home['content_type'] or '内容类型未知'}",
            15,
        ),
        "indexable": _check(
            "允许索引",
            accessible and not noindex,
            "未发现 noindex 指令" if not noindex else "页面明确包含 noindex 指令",
            10,
        ),
        "title": _check("页面标题", bool(page.title), page.title or "未找到 title", 8),
        "description": _check(
            "页面摘要",
            bool(page.meta_description),
            page.meta_description or "未找到 meta description",
            8,
        ),
        "canonical": _check(
            "规范地址",
            bool(canonical),
            canonical or "未找到 canonical",
            8,
        ),
        "server_visible_content": _check(
            "服务端可读正文",
            server_visible,
            f"原始 HTML 中可读正文 {visible_length} 个字符"
            + ("；页面主要依赖 JavaScript 渲染" if client_rendering_required else ""),
            18,
        ),
        "headings": _check(
            "内容层级",
            headings_present,
            f"H1 {len(page.headings['h1'])} 个 · H2 {len(page.headings['h2'])} 个",
            8,
        ),
        "structured_data": _check(
            "结构化数据",
            structured_present,
            "、".join(structured_types) if structured_types else "未找到 JSON-LD 类型",
            8,
        ),
        "brand_visible": _check(
            "品牌正文",
            brand_visible,
            "原始正文可直接读取品牌名称" if brand_visible else "原始正文中未读取到品牌名称",
            7,
        ),
        "external_sources": _check(
            "外部引用",
            bool(external_links),
            f"发现 {len(external_links)} 个外部来源链接" if external_links else "未发现外部来源链接",
            4,
        ),
        "robots": _check(
            "robots.txt",
            robots_ok,
            f"HTTP {robots['status_code']}" if robots["status_code"] is not None else "请求失败",
            3,
        ),
        "sitemap": _check(
            "sitemap.xml",
            sitemap_ok,
            f"HTTP {sitemap['status_code']}" if sitemap["status_code"] is not None else "请求失败",
            3,
        ),
    }
    score = float(sum(item["weight"] for item in checks.values() if item["passed"]))
    status = (
        "ready"
        if score >= 75 and accessible and not noindex and server_visible
        else "needs_work"
        if accessible
        else "blocked"
    )

    findings: list[dict[str, Any]] = []

    def finding(
        code: str, severity: str, title: str, detail: str, recommendation: str
    ) -> None:
        findings.append(
            {
                "code": code,
                "severity": severity,
                "title": title,
                "detail": detail,
                "recommendation": recommendation,
            }
        )

    if not accessible:
        finding(
            "homepage_unavailable",
            "high",
            "首页未返回可用 HTML",
            checks["accessible"]["detail"],
            "确认官网公网状态、重定向和响应类型。",
        )
    if client_rendering_required:
        finding(
            "client_rendering_required",
            "high",
            "原始 HTML 缺少可引用正文",
            checks["server_visible_content"]["detail"],
            "为核心产品说明提供服务端渲染或静态 HTML，避免只返回 JavaScript 外壳。",
        )
    elif not server_visible:
        finding(
            "server_visible_content_thin",
            "high",
            "服务端正文信息不足",
            checks["server_visible_content"]["detail"],
            "在原始 HTML 中提供完整的产品定位、能力、适用范围和边界。",
        )
    if not page.meta_description:
        finding(
            "meta_description_missing",
            "medium",
            "页面摘要缺失",
            "原始 HTML 未找到 meta description。",
            "增加准确描述春秋元泉产品与适用场景的页面摘要。",
        )
    if not canonical:
        finding(
            "canonical_missing",
            "medium",
            "规范地址缺失",
            "原始 HTML 未找到 canonical。",
            "为首页声明唯一规范 URL。",
        )
    if not headings_present:
        finding(
            "headings_missing",
            "medium",
            "内容层级不可识别",
            checks["headings"]["detail"],
            "使用一个明确 H1，并用 H2 组织产品能力、场景、证据和常见问题。",
        )
    if not structured_present:
        finding(
            "structured_data_missing",
            "medium",
            "结构化数据缺失",
            "未找到 JSON-LD。",
            "按真实页面内容增加 Organization、SoftwareApplication 或 FAQPage 等适用类型。",
        )
    if not robots_ok:
        finding(
            "robots_unavailable",
            "low",
            "robots.txt 不可回读",
            checks["robots"]["detail"],
            "提供可访问的 robots.txt，并明确允许抓取公开内容。",
        )
    if not sitemap_ok:
        finding(
            "sitemap_unavailable",
            "low",
            "sitemap.xml 不可回读",
            checks["sitemap"]["detail"],
            "提供包含核心产品、方案和说明页面的 sitemap.xml。",
        )

    discovery_documents = {
        kind: {
            "url": document["url"],
            "status_code": document["status_code"],
            "content_type": document["content_type"],
            "headers": document["headers"],
            "body": document["body"],
            "sha256": document["sha256"],
            "size_bytes": document["size_bytes"],
            "truncated": document["truncated"],
            "redirects": document.get("redirects", []),
            "error": document.get("error"),
        }
        for kind, document in discovery.items()
    }
    artifact_manifest = [_artifact(home, "homepage")]
    artifact_manifest.extend(
        _artifact(document, kind)
        for kind, document in discovery.items()
        if document.get("sha256")
    )
    return {
        "requested_url": normalized,
        "final_url": home["url"],
        "status": status,
        "status_code": home["status_code"],
        "content_type": home["content_type"],
        "title": page.title or None,
        "meta_description": page.meta_description or None,
        "canonical_url": canonical or None,
        "score": score,
        "checks": checks,
        "findings": findings,
        "response_headers": home["headers"],
        "raw_html": html,
        "raw_html_sha256": home["sha256"],
        "raw_html_size": home["size_bytes"],
        "discovery_documents": discovery_documents,
        "artifact_manifest": artifact_manifest,
        "response_ms": round((perf_counter() - started) * 1000),
        "checked_at": datetime.now(timezone.utc),
        "audit_version": AUDIT_VERSION,
    }
