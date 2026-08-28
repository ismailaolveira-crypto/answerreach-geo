#!/usr/bin/env python3
"""Build reproducible GEO Article Assistant archives for product download and rollback."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/geo-article-assistant-extension"
VERSION = json.loads((SOURCE / "manifest.json").read_text())["version"]
PUBLIC_ARCHIVE = ROOT / f"apps/web/public/downloads/geo-article-assistant-{VERSION}.zip"
ROLLBACK_ARCHIVE = Path.home() / f".local/share/chunqiu-yuanquan-geo/extensions/geo-article-assistant-{VERSION}-clean.zip"
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
PREFIX = "geo-article-assistant-extension/"


PUBLIC_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(PUBLIC_ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
    for relative in RUNTIME_FILES:
        source = SOURCE / relative
        info = zipfile.ZipInfo(PREFIX + relative, date_time=(2026, 8, 24, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        bundle.writestr(info, source.read_bytes())

ROLLBACK_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(PUBLIC_ARCHIVE, ROLLBACK_ARCHIVE)
digest = hashlib.sha256(PUBLIC_ARCHIVE.read_bytes()).hexdigest()
print(f"packaged {PUBLIC_ARCHIVE.relative_to(ROOT)} · sha256={digest}")
