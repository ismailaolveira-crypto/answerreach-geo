"""Isolated Playwright capture pinned to a previously validated public address."""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Route, sync_playwright


def _port(parsed) -> int:
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _allowed_request(url: str, *, host: str, port: int, scheme: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme in {"data", "blob"}:
        return True
    if parsed.scheme != scheme or not parsed.hostname:
        return False
    try:
        request_port = _port(parsed)
    except ValueError:
        return False
    return parsed.hostname.lower().rstrip(".") == host and request_port == port


def _install_network_policy(
    context: BrowserContext, *, host: str, port: int, scheme: str
) -> None:
    def route_request(route: Route) -> None:
        if _allowed_request(route.request.url, host=host, port=port, scheme=scheme):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    # Context-wide routing also covers the first request of popups and any
    # additional pages created by untrusted site JavaScript.
    context.route("**/*", route_request)
    # Captures never need a bidirectional socket. Routed WebSockets do not
    # connect unless explicitly forwarded; close them fail-closed.
    context.route_web_socket(
        "**/*",
        lambda socket: socket.close(code=1008, reason="network policy"),
    )


def capture(
    *,
    url: str,
    approved_host: str,
    approved_address: str,
    approved_port: int,
    output: Path,
) -> None:
    parsed = urlsplit(url)
    host = approved_host.lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid_capture_url")
    if parsed.hostname.lower().rstrip(".") != host or _port(parsed) != approved_port:
        raise ValueError("capture_origin_mismatch")
    address = ipaddress.ip_address(approved_address)
    if not address.is_global:
        raise ValueError("capture_address_not_public")

    resolver_address = f"[{address.compressed}]" if address.version == 6 else address.compressed
    resolver_rule = f"MAP {host} {resolver_address}, EXCLUDE localhost"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                f"--host-resolver-rules={resolver_rule}",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-first-run",
            ],
        )
        try:
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                service_workers="block",
                accept_downloads=False,
                ignore_https_errors=False,
            )
            _install_network_policy(
                context,
                host=host,
                port=approved_port,
                scheme=parsed.scheme,
            )
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if response is None or response.status >= 400:
                raise RuntimeError("capture_page_not_readable")
            final = urlsplit(page.url)
            if (
                final.scheme != parsed.scheme
                or not final.hostname
                or final.hostname.lower().rstrip(".") != host
                or _port(final) != approved_port
            ):
                raise RuntimeError("capture_redirected_off_origin")
            page.wait_for_timeout(5_000)
            material = page.evaluate(
                """() => ({
                  htmlLength: document.documentElement.outerHTML.length,
                  textLength: (document.body?.innerText || '').trim().length,
                  imageCount: document.images.length,
                  canvasCount: document.querySelectorAll('canvas').length
                })"""
            )
            if int(material.get("htmlLength") or 0) < 200 or not (
                int(material.get("textLength") or 0) >= 40
                or int(material.get("imageCount") or 0) > 0
                or int(material.get("canvasCount") or 0) > 0
            ):
                raise RuntimeError("capture_page_has_no_visible_material")
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), full_page=False)
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--approved-host", required=True)
    parser.add_argument("--approved-address", required=True)
    parser.add_argument("--approved-port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture(
        url=args.url,
        approved_host=args.approved_host,
        approved_address=args.approved_address,
        approved_port=args.approved_port,
        output=args.output,
    )


if __name__ == "__main__":
    main()
