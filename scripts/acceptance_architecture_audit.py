#!/usr/bin/env python3
"""Cheap structural guardrails for deployment and supply-chain boundaries."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
action_refs = re.findall(r"^\s*- uses:\s*([^\s#]+)", workflow, flags=re.MULTILINE)
for reference in action_refs:
    owner_action, separator, version = reference.rpartition("@")
    require(bool(owner_action and separator), f"invalid GitHub Action reference: {reference}")
    require(
        bool(re.fullmatch(r"[0-9a-f]{40}", version)),
        f"GitHub Action must use an immutable commit SHA: {reference}",
    )

image_files = [
    ROOT / "apps/api/Dockerfile",
    ROOT / "apps/web/Dockerfile",
    ROOT / "infra/docker-compose.personal.yml",
    ROOT / "infra/docker-compose.lan.yml",
    ROOT / "infra/docker-compose.cloud.yml",
]
image_pattern = re.compile(r"(?:^FROM\s+|^\s*image:\s*)([^\s]+)", re.MULTILINE)
for path in image_files:
    content = path.read_text(encoding="utf-8")
    stage_aliases = set(
        re.findall(r"^FROM\s+[^\s]+\s+AS\s+([A-Za-z0-9_.-]+)", content, re.MULTILINE)
    )
    for image in image_pattern.findall(content):
        if image in stage_aliases:
            continue
        if image.startswith("${"):
            continue
        require(
            bool(re.search(r"@sha256:[0-9a-f]{64}$", image)),
            f"container image must be pinned by digest: {path.relative_to(ROOT)} -> {image}",
        )

require(
    not (ROOT / "infra/docker-compose.yml").exists(),
    "obsolete insecure infra/docker-compose.yml must not be restored",
)
for name in ("personal", "lan", "cloud"):
    compose = (ROOT / f"infra/docker-compose.{name}.yml").read_text(encoding="utf-8")
    require("--no-access-log" in compose, f"{name} API must not log secret-bearing URLs")

db_audit = (ROOT / "scripts/acceptance_db_audit.py").read_text(encoding="utf-8")
require("20260830_0041" in db_audit, "database audit is not aligned with migration 0041")

print(
    "architecture audit: ok · immutable actions/images · safe access logs · migration 0041"
)
