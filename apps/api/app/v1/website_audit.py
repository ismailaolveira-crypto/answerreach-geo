from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import html
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
BRAND_FACT_SCRIPT_MAX_BYTES = 2 * 1024 * 1024
BRAND_FACT_SCRIPT_TOTAL_BYTES = 5 * 1024 * 1024
BRAND_FACT_SCRIPT_MAX_FILES = 8
BRAND_FACT_CANDIDATE_LIMIT = 10
BRAND_FACT_CANDIDATE_MIN_HAN = 8
BRAND_FACT_CANDIDATE_MAX_CHARS = 220
_NON_FACTUAL_CANDIDATE_PHRASES = (
    "登录",
    "注册",
    "下载",
    "忘记密码",
    "欢迎回来",
    "联系我们",
    "申请产品体验",
    "开始使用",
    "功能暂未开放",
)


class WebsiteAuditTargetError(ValueError):
    """Raised when a configured workspace URL is unsafe or unsupported."""


class PublicationVerificationError(ValueError):
    """Raised when a claimed public page cannot be verified as readable HTML."""


class BrandFactSourceVerificationError(ValueError):
    """Raised when a public page does not prove the submitted brand statement."""


Resolver = Callable[[str, int], list[str]]


@dataclass(frozen=True)
class ResolvedPublicTarget:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]
    authority: str


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


def _resolve_public_target(url: str, *, resolver: Resolver) -> ResolvedPublicTarget:
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
    validated_addresses: list[str] = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise WebsiteAuditTargetError("website_url_dns_invalid") from exc
        if not ip.is_global:
            raise WebsiteAuditTargetError("website_url_private_network_blocked")
        validated_addresses.append(ip.compressed)
    normalized_path = parsed.path or "/"
    normalized = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, normalized_path, parsed.query, "")
    )
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    authority = host if port == default_port else f"{host}:{port}"
    return ResolvedPublicTarget(
        url=normalized,
        host=host,
        port=port,
        addresses=tuple(sorted(set(validated_addresses))),
        authority=authority,
    )


def _validate_public_url(url: str, *, resolver: Resolver) -> str:
    return _resolve_public_target(url, resolver=resolver).url


def _pinned_url(target: ResolvedPublicTarget, address: str) -> str:
    parsed = urlsplit(target.url)
    ip = ipaddress.ip_address(address)
    host = f"[{ip.compressed}]" if ip.version == 6 else ip.compressed
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = host if target.port == default_port else f"{host}:{target.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


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
        target = _resolve_public_target(current, resolver=resolver)
        current = target.url
        approved_address = target.addresses[0]
        with client.stream(
            "GET",
            _pinned_url(target, approved_address),
            headers={"Host": target.authority},
            extensions={"sni_hostname": target.host},
            follow_redirects=False,
        ) as response:
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
        trust_env=False,
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


def verify_structured_data_page(
    url: str,
    *,
    expected_types: list[str] | None = None,
    resolver: Resolver = _default_resolver,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Safely fetch public HTML and deterministically validate its JSON-LD types."""
    owned_client = client is None
    active_client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=httpx.Timeout(12.0, connect=8.0),
        follow_redirects=False,
        trust_env=False,
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
        raise PublicationVerificationError("structured_data_request_failed") from exc
    finally:
        if owned_client:
            active_client.close()
    status_code = int(document.get("status_code") or 0)
    if status_code < 200 or status_code >= 400:
        raise PublicationVerificationError(f"structured_data_http_{status_code or 'unknown'}")
    content_type = str(document.get("content_type") or "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise PublicationVerificationError("structured_data_page_not_html")
    parser = _PageParser()
    parser.feed(str(document.get("body") or ""))
    structured_types = sorted(set(parser.page.structured_types))
    if not structured_types:
        raise PublicationVerificationError("structured_data_missing")
    required_types = sorted({str(value).strip() for value in expected_types or [] if str(value).strip()})
    missing_types = sorted(set(required_types) - set(structured_types))
    if missing_types:
        raise PublicationVerificationError(
            "structured_data_types_missing:" + ",".join(missing_types)
        )
    return {
        "status": "schema_validated",
        "verified_url": document["url"],
        "status_code": status_code,
        "content_type": content_type,
        "sha256": document["sha256"],
        "size_bytes": document["size_bytes"],
        "structured_types": structured_types,
        "expected_types": required_types,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_brand_fact_source(
    url: str,
    statement: str,
    *,
    resolver: Resolver = _default_resolver,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Verify a statement in public HTML or bounded same-origin frontend resources."""

    if client is None:
        with httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/javascript",
            },
            timeout=httpx.Timeout(12.0, connect=8.0),
            follow_redirects=False,
            trust_env=False,
        ) as owned_client:
            return verify_brand_fact_source(
                url,
                statement,
                resolver=resolver,
                client=owned_client,
            )
    active_client = client
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
    status_code = int(document.get("status_code") or 0)
    if status_code < 200 or status_code >= 300:
        raise BrandFactSourceVerificationError(
            f"brand_fact_source_http_{status_code or 'unknown'}"
        )
    content_type = str(document.get("content_type") or "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise BrandFactSourceVerificationError("brand_fact_source_not_html")

    normalized_statement = re.sub(r"\s+", "", statement.strip())
    if not normalized_statement:
        raise BrandFactSourceVerificationError("brand_fact_statement_not_found")

    parser = _PageParser()
    parser.feed(str(document.get("body") or ""))
    visible_text = re.sub(r"\s+", "", parser.page.body_text)
    evidence = document
    verification_mode = "server_rendered_html"

    if normalized_statement not in visible_text:
        evidence = None
        for script in _same_origin_script_documents(
            document,
            parser,
            client=active_client,
            resolver=resolver,
        ):
            script_body = str(script.get("body") or "")
            if _script_contains_statement(script_body, normalized_statement):
                evidence = script
                verification_mode = "same_origin_public_javascript"
                break

        if evidence is None:
            raise BrandFactSourceVerificationError("brand_fact_statement_not_found")

    return {
        "status": "source_and_statement_verified",
        "verified_url": document["url"],
        "verification_mode": verification_mode,
        "evidence_url": evidence["url"],
        "status_code": int(evidence.get("status_code") or 0),
        "content_type": str(evidence.get("content_type") or "")
        .split(";", 1)[0]
        .strip()
        .lower(),
        "source_sha256": evidence["sha256"],
        "source_page_sha256": document["sha256"],
        "statement_sha256": sha256(statement.strip().encode("utf-8")).hexdigest(),
        "size_bytes": evidence["size_bytes"],
        "truncated": bool(evidence.get("truncated")),
        "redirect_count": len(document.get("redirects") or [])
        + (0 if evidence is document else len(evidence.get("redirects") or [])),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


_JS_STRING_PROPERTY = re.compile(
    r"(?P<key>title|desc|subtitle|badge|pain|solution)\s*:\s*"
    r"(?P<quote>[\"'])(?P<value>(?:\\.|(?!\2).)*)\2",
    re.DOTALL,
)
_JS_PATH = re.compile(r'["\']([^"\']+\.js(?:\?[^"\']*)?)["\']')
_PRODUCT_TERMS = (
    "Token",
    "AI",
    "模型",
    "调用",
    "权限",
    "审计",
    "私有化",
    "成本",
    "调度",
    "安全",
    "治理",
    "数据",
    "密钥",
    "监控",
    "Gateway",
)


def _decode_js_string(value: str) -> str:
    def replace_escape(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("u") and len(token) == 5:
            try:
                return chr(int(token[1:], 16))
            except ValueError:
                return match.group(0)
        if token.startswith("x") and len(token) == 3:
            try:
                return chr(int(token[1:], 16))
            except ValueError:
                return match.group(0)
        return {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "b": "\b",
            "f": "\f",
            "v": "\v",
            "0": "\0",
            "/": "/",
            "\\": "\\",
            '"': '"',
            "'": "'",
        }.get(token, token)

    decoded = re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", replace_escape, value)
    return re.sub(r"\s+", " ", html.unescape(decoded)).strip()


def _script_contains_statement(script_body: str, normalized_statement: str) -> bool:
    if normalized_statement in re.sub(r"\s+", "", script_body):
        return True
    return any(
        normalized_statement in re.sub(r"\s+", "", _decode_js_string(match.group("value")))
        for match in _JS_STRING_PROPERTY.finditer(script_body)
    )


def _same_origin_script_documents(
    document: dict[str, Any],
    parser: _PageParser,
    *,
    client: httpx.Client,
    resolver: Resolver,
) -> list[dict[str, Any]]:
    source_origin = urlsplit(str(document["url"]))
    source_port = source_origin.port or (443 if source_origin.scheme == "https" else 80)
    queued = [urljoin(str(document["url"]), item) for item in parser.page.script_sources]
    seen: set[str] = set()
    total_bytes = 0
    scripts: list[dict[str, Any]] = []

    while queued and len(seen) < BRAND_FACT_SCRIPT_MAX_FILES:
        candidate = queued.pop(0)
        candidate_url = urlsplit(candidate)
        candidate_port = candidate_url.port or (
            443 if candidate_url.scheme == "https" else 80
        )
        if (
            candidate_url.scheme != source_origin.scheme
            or candidate_url.hostname != source_origin.hostname
            or candidate_port != source_port
            or candidate in seen
        ):
            continue
        seen.add(candidate)
        remaining = BRAND_FACT_SCRIPT_TOTAL_BYTES - total_bytes
        if remaining <= 0:
            break
        try:
            script = _fetch(
                client,
                candidate,
                resolver=resolver,
                max_bytes=min(BRAND_FACT_SCRIPT_MAX_BYTES, remaining),
            )
        except (httpx.HTTPError, WebsiteAuditTargetError, OSError):
            continue
        total_bytes += int(script.get("size_bytes") or 0)
        script_origin = urlsplit(str(script.get("url") or ""))
        script_port = script_origin.port or (
            443 if script_origin.scheme == "https" else 80
        )
        script_status = int(script.get("status_code") or 0)
        script_type = str(script.get("content_type") or "").split(";", 1)[0].strip().lower()
        if (
            script_origin.scheme != source_origin.scheme
            or script_origin.hostname != source_origin.hostname
            or script_port != source_port
            or script_status < 200
            or script_status >= 300
            or script_type
            not in {
                "application/javascript",
                "application/ecmascript",
                "text/javascript",
                "text/ecmascript",
            }
        ):
            continue
        scripts.append(script)
        nested_urls = [urljoin(str(script["url"]), path) for path in _JS_PATH.findall(str(script.get("body") or ""))]
        # Follow the dependency closest to the current page first. This keeps an SPA's
        # public copy chunk inside the same fixed file/byte budget.
        for nested in reversed(nested_urls):
            if nested not in seen and nested not in queued:
                queued.insert(0, nested)

    return scripts


def _candidate_query_score(text: str, query_text: str) -> int:
    def bigrams(value: str) -> set[str]:
        normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())
        return {normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))}

    query_bigrams = bigrams(query_text)
    if not query_bigrams:
        return 0
    overlap = len(query_bigrams & bigrams(text))
    return min(60, overlap * 5)


def _candidate_score(
    text: str,
    *,
    brand_name: str,
    query_text: str,
    source_field: str,
    server_visible: bool,
) -> int:
    score = 30 if server_visible else 10
    if brand_name and brand_name.lower() in text.lower():
        score += 35
    term_hits = sum(1 for term in _PRODUCT_TERMS if term.lower() in text.lower())
    score += min(term_hits, 6) * 5
    score += {"desc": 8, "solution": 7, "subtitle": 6, "title": 5, "pain": 4}.get(source_field, 0)
    if 24 <= len(text) <= 150:
        score += 5
    if re.search(r"[。！？；，]", text):
        score += 3
    return score + _candidate_query_score(text, query_text)


def _brand_fact_candidate(
    text: str,
    *,
    brand_name: str,
    query_text: str,
    source_url: str,
    evidence: dict[str, Any],
    source_page_sha256: str,
    verification_mode: str,
    source_field: str,
) -> dict[str, Any] | None:
    value = re.sub(r"\s+", " ", html.unescape(text)).strip(" \t\r\n-–—·")
    if not value or len(value) > BRAND_FACT_CANDIDATE_MAX_CHARS:
        return None
    if (
        verification_mode == "same_origin_public_javascript"
        and source_field == "title"
        and len(value) < 18
    ):
        return None
    if any(phrase in value for phrase in _NON_FACTUAL_CANDIDATE_PHRASES):
        return None
    if re.search(r"<[^>]+>|https?://|sourceMappingURL|webpack|function\s*\(", value, re.I):
        return None
    if len(re.findall(r"[\u4e00-\u9fff]", value)) < BRAND_FACT_CANDIDATE_MIN_HAN:
        return None
    term_hits = sum(1 for term in _PRODUCT_TERMS if term.lower() in value.lower())
    mentions_brand = bool(brand_name and brand_name.lower() in value.lower())
    if (mentions_brand and term_hits < 1) or (not mentions_brand and term_hits < 2):
        return None
    return {
        "statement": value,
        "source_url": source_url,
        "evidence_url": str(evidence["url"]),
        "verification_mode": verification_mode,
        "source_field": source_field,
        "source_sha256": str(evidence["sha256"]),
        "source_page_sha256": source_page_sha256,
        "score": _candidate_score(
            value,
            brand_name=brand_name,
            query_text=query_text,
            source_field=source_field,
            server_visible=verification_mode == "server_rendered_html",
        ),
    }


def discover_brand_fact_source_candidates(
    url: str,
    *,
    brand_name: str,
    query_text: str = "",
    resolver: Resolver = _default_resolver,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return bounded public-copy suggestions for human selection, never auto-save them."""

    if client is None:
        with httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/javascript",
            },
            timeout=httpx.Timeout(12.0, connect=8.0),
            follow_redirects=False,
            trust_env=False,
        ) as owned_client:
            return discover_brand_fact_source_candidates(
                url,
                brand_name=brand_name,
                query_text=query_text,
                resolver=resolver,
                client=owned_client,
            )
    try:
        document = _fetch(
            client,
            url,
            resolver=resolver,
            max_bytes=BRAND_FACT_VERIFY_MAX_BYTES,
        )
    except WebsiteAuditTargetError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise BrandFactSourceVerificationError("brand_fact_source_request_failed") from exc
    status_code = int(document.get("status_code") or 0)
    if status_code < 200 or status_code >= 300:
        raise BrandFactSourceVerificationError(f"brand_fact_source_http_{status_code or 'unknown'}")
    content_type = str(document.get("content_type") or "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise BrandFactSourceVerificationError("brand_fact_source_not_html")

    parser = _PageParser()
    parser.feed(str(document.get("body") or ""))
    candidate_rows: list[dict[str, Any]] = []
    visible_values = [
        (parser.page.title, "title"),
        (parser.page.meta_description, "description"),
        *[(value, "heading") for value in parser.page.headings["h1"]],
        *[(value, "heading") for value in parser.page.headings["h2"]],
        *[(value, "visible_text") for value in parser.page.body_text_parts],
    ]
    for value, source_field in visible_values:
        candidate = _brand_fact_candidate(
            value,
            brand_name=brand_name,
            query_text=query_text,
            source_url=str(document["url"]),
            evidence=document,
            source_page_sha256=str(document["sha256"]),
            verification_mode="server_rendered_html",
            source_field=source_field,
        )
        if candidate:
            candidate_rows.append(candidate)

    scripts = _same_origin_script_documents(
        document,
        parser,
        client=client,
        resolver=resolver,
    )
    for script in scripts:
        for match in _JS_STRING_PROPERTY.finditer(str(script.get("body") or "")):
            value = _decode_js_string(match.group("value"))
            candidate = _brand_fact_candidate(
                value,
                brand_name=brand_name,
                query_text=query_text,
                source_url=str(document["url"]),
                evidence=script,
                source_page_sha256=str(document["sha256"]),
                verification_mode="same_origin_public_javascript",
                source_field=match.group("key"),
            )
            if candidate:
                candidate_rows.append(candidate)

    deduplicated: dict[str, dict[str, Any]] = {}
    for candidate in candidate_rows:
        identity = re.sub(r"\s+", "", str(candidate["statement"])).lower()
        current = deduplicated.get(identity)
        if current is None or int(candidate["score"]) > int(current["score"]):
            deduplicated[identity] = candidate
    candidates = sorted(
        deduplicated.values(),
        key=lambda item: (-int(item["score"]), str(item["statement"])),
    )[:BRAND_FACT_CANDIDATE_LIMIT]
    return {
        "source_url": str(document["url"]),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(candidates),
        "candidates": candidates,
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
