#!/usr/bin/env python3
"""Verify that the distributable extension archive exactly matches source files."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/geo-article-assistant-extension"
VERSION = json.loads((SOURCE / "manifest.json").read_text())["version"]
PUBLIC_ARCHIVE = ROOT / f"apps/web/public/downloads/geo-article-assistant-{VERSION}.zip"
ROLLBACK_ARCHIVE = Path.home() / f".local/share/chunqiu-yuanquan-geo/extensions/geo-article-assistant-{VERSION}-clean.zip"
PREFIX = "geo-article-assistant-extension/"
RUNTIME_FILES = [
    "manifest.json",
    "background.js",
    "content-script.js",
    "page-bridge.js",
    "platform-data.js",
    "popup.html",
    "popup.css",
    "popup.js",
    "platforms.html",
    "platforms.css",
    "platforms.js",
    "rules/platform-headers.json",
    "vendor/adapter-bridge.ts",
    "vendor/wechatsync-adapters.js",
    "vendor/UPSTREAM.md",
    "vendor/wechatsync-core/LICENSE",
    "LICENSE",
    "NOTICE.md",
    "README.md",
]
RUNTIME_FILES += sorted(
    str(path.relative_to(SOURCE))
    for folder in (SOURCE / "assets", SOURCE / "vendor/wechatsync-core/src")
    for path in folder.rglob("*")
    if path.is_file()
)

expected = {
    PREFIX + relative: (SOURCE / relative).read_bytes()
    for relative in RUNTIME_FILES
}
for archive in (PUBLIC_ARCHIVE, ROLLBACK_ARCHIVE):
    with zipfile.ZipFile(archive) as bundle:
        actual_names = {name for name in bundle.namelist() if not name.endswith("/")}
        if actual_names != set(expected):
            missing = sorted(set(expected) - actual_names)
            extra = sorted(actual_names - set(expected))
            raise SystemExit(f"extension archive members differ in {archive}: missing={missing}, extra={extra}")
        changed = [name for name, content in expected.items() if bundle.read(name) != content]
        if changed:
            raise SystemExit(f"extension archive content differs in {archive}: " + ", ".join(changed))
if PUBLIC_ARCHIVE.read_bytes() != ROLLBACK_ARCHIVE.read_bytes():
    raise SystemExit("public and rollback extension archives differ")

digest = hashlib.sha256(PUBLIC_ARCHIVE.read_bytes()).hexdigest()
print(f"extension artifact: ok · sha256={digest}")
