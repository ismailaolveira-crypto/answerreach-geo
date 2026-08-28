#!/usr/bin/env python3
"""Fail when forbidden runtime data or credential-shaped literals enter product source."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
tracked = subprocess.run(
    ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
).stdout.splitlines()
forbidden_path = re.compile(r"(^|/)(\.env[^/]*|geo_platform\.db|private_artifacts|node_modules|\.next)(/|$)|\.log$")
bad_paths = [path for path in tracked if forbidden_path.search(path)]
if bad_paths:
    raise SystemExit("forbidden tracked paths: " + ", ".join(bad_paths))

secret_patterns = [
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{24,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
scan_roots = [ROOT / "apps/api/app", ROOT / "apps/web", ROOT / "apps/geo-article-assistant-extension", ROOT / "docs"]
bad_literals: list[str] = []
for scan_root in scan_roots:
    for path in scan_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if {"node_modules", ".next", ".venv", "private_artifacts", "__pycache__"}.intersection(relative.parts):
            continue
        if path.name.startswith(".env") or path.suffix in {".db", ".sqlite", ".sqlite3", ".pyc"}:
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if any(pattern.search(content) for pattern in secret_patterns):
            bad_literals.append(relative.as_posix())
if bad_literals:
    raise SystemExit("credential-shaped literals found in: " + ", ".join(sorted(bad_literals)))

print("privacy audit: ok")
