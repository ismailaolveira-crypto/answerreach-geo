#!/usr/bin/env python3
"""Validate the portable scope bundle without accessing application state."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    manifest = payload.get("scope_manifest") or {}
    evidence = payload.get("evidence") or []
    allowed = {int(value) for value in manifest.get("eligible_evidence_ids") or []}
    actual = {int(row.get("evidence_id") or 0) for row in evidence}
    if not manifest.get("batch_id") or not allowed or actual != allowed:
        raise SystemExit("scope bundle is incomplete or evidence IDs do not match")
    if any(not row.get("answer_hash") for row in evidence):
        raise SystemExit("scope evidence is missing an answer hash")
    print(json.dumps({"valid": True, "evidence_count": len(actual)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
