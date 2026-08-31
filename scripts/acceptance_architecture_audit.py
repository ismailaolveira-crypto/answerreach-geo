#!/usr/bin/env python3
"""Cheap structural guardrails for deployment and supply-chain boundaries."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


require((ROOT / "pnpm-lock.yaml").is_file(), "pnpm-lock.yaml is required")
require(not (ROOT / "package-lock.json").exists(), "package-lock.json must not coexist with pnpm")

web_source_roots = [ROOT / "apps/web/app", ROOT / "apps/web/src"]
web_sources = [
    path
    for source_root in web_source_roots
    for path in source_root.rglob("*")
    if path.suffix in {".ts", ".tsx"}
]
api_config = ROOT / "apps/web/src/lib/api-config.ts"
session_security = ROOT / "apps/web/src/lib/session-security.ts"
for path in web_sources:
    source = path.read_text(encoding="utf-8")
    if path != api_config:
        require(
            "INTERNAL_API_BASE_URL" not in source
            and "NEXT_PUBLIC_API_BASE_URL" not in source,
            f"web API base URL must be centralized: {path.relative_to(ROOT)}",
        )
    if path != session_security:
        require(
            '"geo_session"' not in source and "'geo_session'" not in source,
            f"session cookie name must be centralized: {path.relative_to(ROOT)}",
        )

modern_geo_root = ROOT / "apps/web/app/(app)/geo"
for path in modern_geo_root.rglob("*"):
    if path.suffix not in {".ts", ".tsx"}:
        continue
    require(
        'from "@/app/actions"' not in path.read_text(encoding="utf-8"),
        f"modern GEO code must use co-located server actions: {path.relative_to(ROOT)}",
    )

line_limits = {
    ROOT / "apps/api/app/v1/routes.py": 2500,
    ROOT / "apps/web/app/(app)/geo/[workspaceId]/actions/priority-actions-workbench.tsx": 1500,
    ROOT / "apps/web/app/actions.ts": 2000,
    ROOT / "apps/web/src/lib/cleanroom-v1-api.ts": 3600,
}
for path, maximum in line_limits.items():
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    require(
        line_count <= maximum,
        f"module boundary regressed: {path.relative_to(ROOT)} has {line_count} lines (max {maximum})",
    )


def module_name(path: Path, package_root: Path) -> str:
    relative = path.relative_to(package_root.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def application_import_graph() -> dict[str, set[str]]:
    package_root = ROOT / "apps/api/app"
    modules = {
        module_name(path, package_root): path
        for path in package_root.rglob("*.py")
    }
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                candidates.append(node.module)
                candidates.extend(f"{node.module}.{alias.name}" for alias in node.names)
            for candidate in candidates:
                if candidate in modules and candidate != name:
                    graph[name].add(candidate)
                if ".services." in name and (
                    ".api.routes." in candidate
                    or candidate.endswith(".routes")
                    or candidate.endswith("_routes")
                ):
                    raise SystemExit(
                        f"service layer must not import HTTP routes: {name} -> {candidate}"
                    )
    return graph


def import_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    active: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    cycles: list[list[str]] = []

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = lowlinks[module] = index
        index += 1
        stack.append(module)
        active.add(module)
        for dependency in graph[module]:
            if dependency not in indices:
                visit(dependency)
                lowlinks[module] = min(lowlinks[module], lowlinks[dependency])
            elif dependency in active:
                lowlinks[module] = min(lowlinks[module], indices[dependency])
        if lowlinks[module] != indices[module]:
            return
        component: list[str] = []
        while True:
            dependency = stack.pop()
            active.remove(dependency)
            component.append(dependency)
            if dependency == module:
                break
        if len(component) > 1:
            cycles.append(sorted(component))

    for module in graph:
        if module not in indices:
            visit(module)
    return cycles


cycles = import_cycles(application_import_graph())
require(not cycles, f"application import cycle detected: {cycles}")
job_queue_source = (ROOT / "apps/api/app/services/job_queue.py").read_text(encoding="utf-8")
require(
    'db.info["geo_observation_task_id"]' not in job_queue_source,
    "observation task identity must be passed explicitly",
)


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

api_dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
require(
    "apt-get upgrade -y" in api_dockerfile,
    "API image must install available Debian security upgrades",
)

web_dockerfile = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")
require(
    "apk upgrade --no-cache" in web_dockerfile,
    "Web runtime image must install available Alpine security upgrades",
)
require(
    "rm -rf /usr/local/lib/node_modules/npm" in web_dockerfile,
    "Web runtime image must not retain build-only npm packages",
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
    "architecture audit: ok · acyclic app imports · service/route boundary · immutable deployment"
)
