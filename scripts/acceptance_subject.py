#!/usr/bin/env python3
"""Print a deterministic hash for the current GEO implementation snapshot."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INCLUDED = (
    ROOT / ".gitignore",
    ROOT / "package.json",
    ROOT / "pnpm-lock.yaml",
    ROOT / "apps/api/app",
    ROOT / "apps/api/migrations",
    ROOT / "apps/api/scripts",
    ROOT / "apps/api/tests",
    ROOT / "apps/web/app",
    ROOT / "apps/web/src",
    ROOT / "apps/web/public",
    ROOT / "apps/web/package.json",
    ROOT / "apps/geo-article-assistant-extension",
    ROOT / "docs",
    ROOT / "scripts",
)
EXCLUDED_PARTS = {
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "private_artifacts",
}


def included_files() -> list[Path]:
    files: set[Path] = set()
    for entry in INCLUDED:
        if entry.is_file():
            files.add(entry)
            continue
        if not entry.is_dir():
            continue
        for path in entry.rglob("*"):
            if not path.is_file() or EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts):
                continue
            if path.name.startswith(".env") or path.suffix in {".db", ".sqlite", ".sqlite3", ".pyc"}:
                continue
            files.add(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


digest = hashlib.sha256()
for file_path in included_files():
    relative = file_path.relative_to(ROOT).as_posix().encode("utf-8")
    digest.update(len(relative).to_bytes(4, "big"))
    digest.update(relative)
    content = file_path.read_bytes()
    digest.update(len(content).to_bytes(8, "big"))
    digest.update(content)

print(digest.hexdigest())
