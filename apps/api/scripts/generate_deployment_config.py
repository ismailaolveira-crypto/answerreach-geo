"""Generate a private compose environment file without printing its secrets."""

from __future__ import annotations

import argparse
import os
import re
import secrets
from pathlib import Path


_CLOUD_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)


def _validate_host(mode: str, host: str | None) -> str | None:
    if mode == "personal":
        return None
    normalized = (host or "").strip().lower().rstrip(".")
    if not normalized:
        raise SystemExit(f"--host is required for {mode} mode")
    if mode == "cloud" and not _CLOUD_DOMAIN_PATTERN.fullmatch(normalized):
        raise SystemExit("--host must be a public domain name, for example geo.example.com")
    if any(character in normalized for character in ("/", ":", " ")):
        raise SystemExit("--host must not contain a URL scheme, path, port, or spaces")
    return normalized


def build_config_lines(*, mode: str, host: str | None, port: int, concurrency: int) -> list[str]:
    normalized_host = _validate_host(mode, host)
    lines = [
        f"GEO_AUTH_SECRET={secrets.token_urlsafe(64)}",
        f"GEO_INTERNAL_PROXY_SECRET={secrets.token_urlsafe(64)}",
        f"GEO_WORKER_CONCURRENCY={concurrency}",
        f"GEO_WORKER_INSTANCE_ID={secrets.token_hex(16)}",
    ]
    if mode in {"personal", "lan"}:
        lines.append(f"GEO_HTTP_PORT={port}")
    if mode == "lan":
        lines.extend(
            [
                f"GEO_LAN_HOST={normalized_host}",
                f"GEO_POSTGRES_PASSWORD={secrets.token_urlsafe(36)}",
            ]
        )
    elif mode == "cloud":
        lines.extend(
            [
                f"GEO_DOMAIN={normalized_host}",
                f"GEO_POSTGRES_PASSWORD={secrets.token_urlsafe(36)}",
            ]
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate private GEO deployment configuration")
    parser.add_argument("--mode", choices=("personal", "lan", "cloud"), required=True)
    parser.add_argument("--host", help="LAN host or cloud domain; required outside personal mode")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    default_concurrency = {"personal": 8, "lan": 125, "cloud": 32}[args.mode]
    concurrency = args.concurrency or default_concurrency
    if not 1 <= concurrency <= 125:
        raise SystemExit("--concurrency must be between 1 and 125")
    output = args.output or Path(f".env.{args.mode}")
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing configuration: {output}")
    lines = build_config_lines(
        mode=args.mode,
        host=args.host,
        port=args.port,
        concurrency=concurrency,
    )
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"Created private {args.mode} configuration at {output} (mode 0600).")


if __name__ == "__main__":
    main()
