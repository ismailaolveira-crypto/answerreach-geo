"""Generate a private compose environment file without printing its secrets."""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local GEO deployment configuration")
    parser.add_argument("--mode", choices=("personal", "lan"), required=True)
    parser.add_argument("--host", help="LAN IP or internal host name; required for LAN mode")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "lan" and not args.host:
        raise SystemExit("--host is required for LAN mode, for example --host 192.168.1.20")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    concurrency = args.concurrency or (8 if args.mode == "personal" else 125)
    if not 1 <= concurrency <= 125:
        raise SystemExit("--concurrency must be between 1 and 125")
    output = args.output or Path(f".env.{args.mode}")
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing configuration: {output}")
    lines = [
        f"GEO_AUTH_SECRET={secrets.token_urlsafe(64)}",
        f"GEO_HTTP_PORT={args.port}",
        f"GEO_WORKER_CONCURRENCY={concurrency}",
        f"GEO_WORKER_INSTANCE_ID={secrets.token_hex(16)}",
    ]
    if args.mode == "lan":
        lines.extend(
            [
                f"GEO_LAN_HOST={args.host}",
                f"GEO_POSTGRES_PASSWORD={secrets.token_urlsafe(36)}",
            ]
        )
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"Created private {args.mode} configuration at {output} (mode 0600).")


if __name__ == "__main__":
    main()
