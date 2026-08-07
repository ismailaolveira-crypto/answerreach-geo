import argparse
import json
import socket
import ssl
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import LLMProvider


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "latest_provider_network_check.json"


def _parse_ids(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _endpoint(provider: LLMProvider) -> tuple[str | None, str | None, int | None]:
    if not provider.api_base_url:
        return None, None, None
    parsed = urlparse(provider.api_base_url)
    host = parsed.hostname
    scheme = parsed.scheme or "https"
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, host, port


def _check_host(host: str, port: int, timeout: float) -> dict[str, Any]:
    started = perf_counter()
    addresses: list[str] = []
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = sorted({item[4][0] for item in infos})
        dns_ok = True
        dns_error = None
    except Exception as exc:
        return {
            "ok": False,
            "dns_ok": False,
            "tcp_ok": False,
            "tls_ok": False,
            "addresses": [],
            "error_stage": "dns",
            "error": str(exc),
            "latency_ms": int((perf_counter() - started) * 1000),
        }

    try:
        raw_socket = socket.create_connection((host, port), timeout=timeout)
        tcp_ok = True
        tcp_error = None
    except Exception as exc:
        return {
            "ok": False,
            "dns_ok": dns_ok,
            "tcp_ok": False,
            "tls_ok": False,
            "addresses": addresses,
            "error_stage": "tcp",
            "error": str(exc),
            "dns_error": dns_error,
            "latency_ms": int((perf_counter() - started) * 1000),
        }

    try:
        with raw_socket:
            context = ssl.create_default_context()
            with context.wrap_socket(raw_socket, server_hostname=host):
                pass
        tls_ok = True
        tls_error = None
    except Exception as exc:
        return {
            "ok": False,
            "dns_ok": dns_ok,
            "tcp_ok": tcp_ok,
            "tls_ok": False,
            "addresses": addresses,
            "error_stage": "tls",
            "error": str(exc),
            "dns_error": dns_error,
            "tcp_error": tcp_error,
            "latency_ms": int((perf_counter() - started) * 1000),
        }

    return {
        "ok": True,
        "dns_ok": dns_ok,
        "tcp_ok": tcp_ok,
        "tls_ok": tls_ok,
        "addresses": addresses,
        "error_stage": None,
        "error": None,
        "dns_error": dns_error,
        "tcp_error": tcp_error,
        "tls_error": tls_error,
        "latency_ms": int((perf_counter() - started) * 1000),
    }


def check_provider_network(
    *,
    provider_ids: list[int] | None,
    output_path: Path,
    timeout: float,
) -> dict[str, Any]:
    with SessionLocal() as db:
        stmt = (
            select(LLMProvider)
            .where(LLMProvider.provider_type.not_in(["mock", "browser_observation"]))
            .order_by(LLMProvider.id.asc())
        )
        if provider_ids:
            stmt = stmt.where(LLMProvider.id.in_(provider_ids))
        providers = list(db.scalars(stmt))

    results: list[dict[str, Any]] = []
    for provider in providers:
        scheme, host, port = _endpoint(provider)
        if not host or not port:
            results.append(
                {
                    "provider_id": provider.id,
                    "name": provider.name,
                    "provider_type": provider.provider_type,
                    "model_name": provider.model_name,
                    "api_base_url": provider.api_base_url,
                    "ok": False,
                    "error_stage": "config",
                    "error": "Missing api_base_url host",
                }
            )
            continue
        check = _check_host(host, port, timeout)
        results.append(
            {
                "provider_id": provider.id,
                "name": provider.name,
                "provider_type": provider.provider_type,
                "model_name": provider.model_name,
                "api_base_url": provider.api_base_url,
                "scheme": scheme,
                "host": host,
                "port": port,
                **check,
            }
        )
    payload = {
        "ok": all(item.get("ok") for item in results) if results else False,
        "verification_method": "dns_tcp_tls_provider_network_preflight",
        "provider_ids": provider_ids,
        "results": results,
        "created_at": datetime.now(UTC).isoformat(),
        "safety": {"api_keys_used": False, "chat_completions_called": False},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Check DNS/TCP/TLS connectivity for real Provider base URLs.")
    parser.add_argument("--provider-ids", default="")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = check_provider_network(
        provider_ids=_parse_ids(args.provider_ids) if args.provider_ids else None,
        output_path=args.output,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
