"""CSV preflight and append-only ROI import operations."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import io
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cleanroom_v1 import (
    GeoBusinessMetricEntry,
    GeoBusinessMetricImportBatch,
    GeoBusinessMetricImportRow,
    GeoOptimizationAction,
)


CANONICAL_FIELDS = [
    "record_id", "occurred_at", "metric_type", "amount", "quantity", "currency",
    "action_id", "attribution_type", "source_type", "source_reference", "source_label",
    "evidence_note",
]
REQUIRED_BASE_FIELDS = {
    "record_id", "occurred_at", "metric_type", "attribution_type", "source_type",
    "source_label", "evidence_note",
}
HEADER_ALIASES = {
    "记录编号": "record_id", "发生时间": "occurred_at", "数据类型": "metric_type",
    "金额": "amount", "数量": "quantity", "币种": "currency", "优化行动": "action_id",
    "归因类型": "attribution_type", "来源类型": "source_type",
    "来源凭证": "source_reference", "来源名称": "source_label", "说明": "evidence_note",
}
ALLOWED_CURRENCIES = {
    "CNY", "USD", "EUR", "GBP", "JPY", "HKD", "SGD", "AUD", "CAD", "CHF",
    "KRW", "INR", "NZD", "SEK", "NOK", "DKK", "AED", "SAR", "THB", "MYR",
}
MAX_FILE_BYTES = 2_000_000
MAX_ROWS = 5_000


def template_csv() -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CANONICAL_FIELDS)
    writer.writerow([
        "cost-202608-001", "2026-08-24T09:00:00+08:00", "content_cost", "1200.00", "",
        "CNY", "1", "not_applicable", "manual_import", "FIN-202608-001", "8月成本表",
        "行动1的内容制作成本",
    ])
    writer.writerow([
        "lead-202608-001", "2026-08-24T10:00:00+08:00", "qualified_lead", "", "3",
        "", "1", "direct", "crm", "CRM-LEAD-001", "CRM 线索表", "AI引荐形成的有效线索",
    ])
    return "\ufeff" + buffer.getvalue()


def _formula_risk(field: str, value: str) -> bool:
    stripped = value.lstrip()
    if not stripped:
        return False
    if stripped[0] in {"=", "+", "@"}:
        return True
    return stripped.startswith("-") and field not in {"amount", "quantity"}


def _mapping(headers: list[str], requested: dict[str, str] | None) -> tuple[dict[str, str], list[dict]]:
    normalized_headers = {header.strip(): header for header in headers if header.strip()}
    mapping: dict[str, str] = {}
    if requested:
        mapping.update({key: value for key, value in requested.items() if key in CANONICAL_FIELDS})
    for header in headers:
        clean = header.strip().lstrip("\ufeff")
        canonical = clean if clean in CANONICAL_FIELDS else HEADER_ALIASES.get(clean)
        if canonical and canonical not in mapping:
            mapping[canonical] = normalized_headers.get(clean, header)
    errors = [
        {"field": field, "code": "missing_column", "message": f"缺少必填列 {field}"}
        for field in sorted(REQUIRED_BASE_FIELDS - set(mapping))
    ]
    if "amount" not in mapping and "quantity" not in mapping:
        errors.append({"field": "amount/quantity", "code": "missing_column", "message": "金额和数量至少需要一列"})
    return mapping, errors


def _normalized_row(raw: dict[str, str | None], mapping: dict[str, str]) -> dict[str, str]:
    return {
        field: str(raw.get(source_header) or "").strip()
        for field, source_header in mapping.items()
    }


def _validate_row(
    db: Session, *, workspace_id: int, row: dict[str, str], known_actions: set[int]
) -> tuple[dict, list[dict]]:
    from app.v1.results_roi_routes import BusinessMetricCreate

    errors: list[dict] = []
    for field, value in row.items():
        if _formula_risk(field, value):
            errors.append({"field": field, "code": "formula_injection", "message": "疑似公式注入内容"})
    record_id = row.get("record_id", "").strip()
    if not record_id:
        errors.append({"field": "record_id", "code": "required", "message": "记录编号不能为空"})
    elif len(record_id) > 160:
        errors.append({"field": "record_id", "code": "too_long", "message": "记录编号不能超过160个字符"})
    occurred_raw = row.get("occurred_at", "")
    action_id = int(row["action_id"]) if row.get("action_id", "").isdigit() else None
    if row.get("action_id") and action_id is None:
        errors.append({"field": "action_id", "code": "invalid_integer", "message": "行动ID必须为整数"})
    elif action_id is not None and action_id not in known_actions:
        errors.append({"field": "action_id", "code": "action_not_found", "message": "行动不存在或不属于当前工作区"})
    currency = row.get("currency", "").upper() or None
    if currency and currency not in ALLOWED_CURRENCIES:
        errors.append({"field": "currency", "code": "invalid_currency", "message": "币种不是支持的 ISO 货币码"})
    amount_raw, quantity_raw = row.get("amount", ""), row.get("quantity", "")
    if amount_raw and quantity_raw:
        errors.append({"field": "amount/quantity", "code": "mutually_exclusive", "message": "金额和数量不能同时填写"})
    try:
        payload = BusinessMetricCreate(
            action_id=action_id,
            metric_type=row.get("metric_type", ""),
            amount=Decimal(amount_raw) if amount_raw else None,
            quantity=float(quantity_raw) if quantity_raw else None,
            currency=currency,
            attribution_type=row.get("attribution_type", ""),
            source_type=row.get("source_type", ""),
            source_label=row.get("source_label", ""),
            source_reference=row.get("source_reference", "") or None,
            evidence_note=row.get("evidence_note", ""),
            occurred_at=occurred_raw,
            idempotency_key=f"csv:{record_id}" if record_id else None,
        )
        occurred = payload.occurred_at
        aware = occurred if occurred.tzinfo else occurred.replace(tzinfo=UTC)
        if aware < datetime(2000, 1, 1, tzinfo=UTC) or aware > datetime.now(UTC) + timedelta(days=1):
            errors.append({"field": "occurred_at", "code": "unreasonable_time", "message": "发生时间超出合理范围"})
    except (ValidationError, ValueError, ArithmeticError) as exc:
        if isinstance(exc, ValidationError):
            for item in exc.errors(include_url=False):
                field = ".".join(str(part) for part in item.get("loc") or ("row",))
                errors.append({"field": field, "code": str(item.get("type") or "invalid"), "message": str(item.get("msg") or "格式错误")})
        else:
            errors.append({"field": "row", "code": "invalid_value", "message": "金额、数量或时间格式错误"})
        payload = None
    normalized: dict = dict(row)
    if payload is not None:
        normalized = {
            "record_id": record_id,
            "occurred_at": payload.occurred_at.isoformat(),
            "metric_type": payload.metric_type,
            "amount": str(payload.amount) if payload.amount is not None else None,
            "quantity": payload.quantity,
            "currency": payload.currency,
            "action_id": payload.action_id,
            "attribution_type": payload.attribution_type,
            "source_type": payload.source_type,
            "source_reference": payload.source_reference,
            "source_label": payload.source_label.strip(),
            "evidence_note": payload.evidence_note.strip(),
        }
    return normalized, errors


def preflight_csv(
    db: Session, *, workspace_id: int, user_id: int, file_name: str, csv_text: str,
    requested_mapping: dict[str, str] | None = None,
) -> GeoBusinessMetricImportBatch:
    encoded = csv_text.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("CSV 文件不能超过 2MB")
    file_sha = sha256(encoded).hexdigest()
    existing = db.scalar(
        select(GeoBusinessMetricImportBatch).where(
            GeoBusinessMetricImportBatch.workspace_id == workspace_id,
            GeoBusinessMetricImportBatch.file_sha256 == file_sha,
        )
    )
    if existing:
        return existing
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    headers = list(reader.fieldnames or [])
    mapping, file_errors = _mapping(headers, requested_mapping)
    raw_rows = list(reader)
    if len(raw_rows) > MAX_ROWS:
        raise ValueError("单次最多导入 5000 行")
    batch = GeoBusinessMetricImportBatch(
        workspace_id=workspace_id,
        file_name=file_name[:255] or "roi-import.csv",
        file_sha256=file_sha,
        status="preflight",
        mapping_json={"mapping": mapping, "file_errors": file_errors},
        total_rows=len(raw_rows),
        created_by_user_id=user_id,
    )
    db.add(batch)
    db.flush()
    known_actions = set(
        db.scalars(select(GeoOptimizationAction.id).where(GeoOptimizationAction.workspace_id == workspace_id))
    )
    existing_record_ids = set(
        value for value in db.scalars(
            select(GeoBusinessMetricEntry.source_record_id).where(
                GeoBusinessMetricEntry.workspace_id == workspace_id,
                GeoBusinessMetricEntry.source_record_id.is_not(None),
            )
        ) if value
    )
    file_record_ids: set[str] = set()
    counts = {"valid": 0, "error": 0, "duplicate": 0}
    for row_number, raw in enumerate(raw_rows, start=2):
        row = _normalized_row(raw, mapping)
        normalized, errors = _validate_row(
            db, workspace_id=workspace_id, row=row, known_actions=known_actions
        )
        errors = [*file_errors, *errors]
        record_id = str(normalized.get("record_id") or row.get("record_id") or "").strip()
        duplicate_message = None
        if record_id and record_id in file_record_ids:
            duplicate_message = "文件内存在重复 record_id"
        elif record_id and record_id in existing_record_ids:
            duplicate_message = "该 record_id 已经导入"
        if duplicate_message:
            status = "duplicate"
            errors.append({"field": "record_id", "code": "duplicate", "message": duplicate_message})
        elif errors:
            status = "error"
        else:
            status = "valid"
        if record_id:
            file_record_ids.add(record_id)
        counts[status] += 1
        db.add(GeoBusinessMetricImportRow(
            workspace_id=workspace_id,
            import_batch_id=batch.id,
            row_number=row_number,
            record_id=record_id or None,
            normalized_json=normalized,
            status=status,
            errors_json=errors,
        ))
    batch.valid_rows = counts["valid"]
    batch.error_rows = counts["error"]
    batch.duplicate_rows = counts["duplicate"]
    db.commit()
    db.refresh(batch)
    return batch


def confirm_import(db: Session, *, batch: GeoBusinessMetricImportBatch, user_id: int) -> int:
    if batch.status == "confirmed":
        return batch.imported_rows
    rows = list(
        db.scalars(
            select(GeoBusinessMetricImportRow).where(
                GeoBusinessMetricImportRow.import_batch_id == batch.id,
                GeoBusinessMetricImportRow.status == "valid",
            ).order_by(GeoBusinessMetricImportRow.row_number)
        )
    )
    imported = 0
    for row in rows:
        data = row.normalized_json or {}
        record_id = str(data.get("record_id") or "")
        duplicate = db.scalar(
            select(GeoBusinessMetricEntry).where(
                GeoBusinessMetricEntry.workspace_id == batch.workspace_id,
                GeoBusinessMetricEntry.idempotency_key == f"csv:{record_id}",
            )
        )
        if duplicate:
            row.status = "duplicate"
            row.metric_entry_id = duplicate.id
            continue
        amount = Decimal(str(data["amount"])) if data.get("amount") is not None else None
        entry = GeoBusinessMetricEntry(
            workspace_id=batch.workspace_id,
            action_id=data.get("action_id"),
            metric_type=data["metric_type"],
            amount_minor=int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if amount is not None else None,
            quantity=data.get("quantity"),
            currency=data.get("currency"),
            attribution_type=data["attribution_type"],
            source_type=data["source_type"],
            source_label=data["source_label"],
            source_reference=data.get("source_reference"),
            evidence_note=data["evidence_note"],
            verification_status="user_confirmed",
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            created_by_user_id=user_id,
            idempotency_key=f"csv:{record_id}",
            import_batch_id=batch.id,
            source_record_id=record_id,
        )
        db.add(entry)
        db.flush()
        row.metric_entry_id = entry.id
        row.status = "imported"
        imported += 1
    batch.status = "confirmed"
    batch.imported_rows = imported
    batch.duplicate_rows = int(
        db.scalar(
            select(func.count(GeoBusinessMetricImportRow.id)).where(
                GeoBusinessMetricImportRow.import_batch_id == batch.id,
                GeoBusinessMetricImportRow.status == "duplicate",
            )
        )
        or 0
    )
    batch.confirmed_at = datetime.now(UTC)
    db.commit()
    return imported


def batch_read(db: Session, batch: GeoBusinessMetricImportBatch, *, include_rows: bool = True) -> dict:
    rows = list(
        db.scalars(
            select(GeoBusinessMetricImportRow)
            .where(GeoBusinessMetricImportRow.import_batch_id == batch.id)
            .order_by(GeoBusinessMetricImportRow.row_number)
        )
    ) if include_rows else []
    return {
        "id": batch.id,
        "file_name": batch.file_name,
        "file_sha256": batch.file_sha256,
        "status": batch.status,
        "mapping": batch.mapping_json,
        "total_rows": batch.total_rows,
        "valid_rows": batch.valid_rows,
        "error_rows": batch.error_rows,
        "duplicate_rows": batch.duplicate_rows,
        "imported_rows": batch.imported_rows,
        "confirmed_at": batch.confirmed_at,
        "reversed_at": batch.reversed_at,
        "created_at": batch.created_at,
        "rows": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "record_id": row.record_id,
                "status": row.status,
                "normalized": row.normalized_json,
                "errors": row.errors_json,
                "metric_entry_id": row.metric_entry_id,
            }
            for row in rows
        ],
    }
