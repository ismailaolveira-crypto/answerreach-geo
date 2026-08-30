from __future__ import annotations

import csv
from datetime import UTC, datetime
import io

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import WRITE_ROLES, get_current_user, require_roles
from app.db.session import get_db
from app.models.cleanroom_v1 import (
    GeoBusinessMetricEntry,
    GeoBusinessMetricImportBatch,
    GeoBusinessMetricImportRow,
)
from app.models.user import User
from app.services.audit import record_audit_log
from app.services.workspace_access import require_workspace_access
from app.v1.roi_csv_imports import batch_read, confirm_import, preflight_csv, template_csv


router = APIRouter(prefix="/v1", tags=["geo-roi-csv-imports-v1"])


def _spreadsheet_safe_cell(value: object) -> object:
    """Keep exported error reports inert in spreadsheet applications."""

    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    return f"'{value}" if stripped.startswith(("=", "+", "-", "@")) else value


class CsvPreflightRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    csv_text: str = Field(min_length=1, max_length=2_000_000)
    mapping: dict[str, str] | None = None


class BatchReverseRequest(BaseModel):
    reason: str = Field(min_length=4, max_length=1000)


def _batch_or_404(db: Session, workspace_id: int, batch_id: int) -> GeoBusinessMetricImportBatch:
    batch = db.get(GeoBusinessMetricImportBatch, batch_id)
    if batch is None or batch.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return batch


@router.get("/workspaces/{workspace_id}/business-metric-imports/template")
def download_business_metric_template(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    return Response(
        content=template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="geo-roi-import-template.csv"'},
    )


@router.post(
    "/workspaces/{workspace_id}/business-metric-imports/preflight",
    status_code=status.HTTP_201_CREATED,
)
def preflight_business_metric_import(
    workspace_id: int,
    payload: CsvPreflightRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    require_workspace_access(db, user, workspace_id)
    try:
        batch = preflight_csv(
            db,
            workspace_id=workspace_id,
            user_id=user.id,
            file_name=payload.file_name,
            csv_text=payload.csv_text,
            requested_mapping=payload.mapping,
        )
    except (ValueError, UnicodeError, csv.Error) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return batch_read(db, batch)


@router.get("/workspaces/{workspace_id}/business-metric-imports")
def list_business_metric_imports(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    rows = list(
        db.scalars(
            select(GeoBusinessMetricImportBatch)
            .where(GeoBusinessMetricImportBatch.workspace_id == workspace_id)
            .order_by(GeoBusinessMetricImportBatch.created_at.desc(), GeoBusinessMetricImportBatch.id.desc())
            .limit(50)
        )
    )
    return [batch_read(db, row, include_rows=False) for row in rows]


@router.get("/workspaces/{workspace_id}/business-metric-imports/{batch_id}")
def read_business_metric_import(
    workspace_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    return batch_read(db, _batch_or_404(db, workspace_id, batch_id))


@router.post("/workspaces/{workspace_id}/business-metric-imports/{batch_id}/confirm")
def confirm_business_metric_import(
    workspace_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    batch = _batch_or_404(db, workspace_id, batch_id)
    imported = confirm_import(db, batch=batch, user_id=user.id)
    record_audit_log(
        db,
        user=user,
        action="geo.business_metric.csv_imported",
        resource_type="geo_business_metric_import",
        resource_id=batch.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace_id, "imported_rows": imported, "file_sha256": batch.file_sha256},
    )
    db.commit()
    db.refresh(batch)
    return batch_read(db, batch)


@router.get("/workspaces/{workspace_id}/business-metric-imports/{batch_id}/errors.csv")
def download_business_metric_import_errors(
    workspace_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_workspace_access(db, user, workspace_id)
    batch = _batch_or_404(db, workspace_id, batch_id)
    rows = list(
        db.scalars(
            select(GeoBusinessMetricImportRow).where(
                GeoBusinessMetricImportRow.import_batch_id == batch.id,
                GeoBusinessMetricImportRow.status.in_(("error", "duplicate")),
            ).order_by(GeoBusinessMetricImportRow.row_number)
        )
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["row_number", "record_id", "status", "field", "error_code", "message"])
    for row in rows:
        for error in row.errors_json or [{"field": "row", "code": "invalid", "message": "需修复"}]:
            writer.writerow([
                row.row_number,
                _spreadsheet_safe_cell(row.record_id or ""),
                row.status,
                _spreadsheet_safe_cell(error.get("field") or "row"),
                _spreadsheet_safe_cell(error.get("code") or "invalid"),
                _spreadsheet_safe_cell(error.get("message") or "需修复"),
            ])
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="geo-roi-import-{batch.id}-errors.csv"'},
    )


@router.post("/workspaces/{workspace_id}/business-metric-imports/{batch_id}/reverse")
def reverse_business_metric_import(
    workspace_id: int,
    batch_id: int,
    payload: BatchReverseRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WRITE_ROLES)),
):
    workspace, _membership = require_workspace_access(db, user, workspace_id)
    batch = _batch_or_404(db, workspace_id, batch_id)
    if batch.status == "reversed":
        return batch_read(db, batch)
    entries = list(
        db.scalars(
            select(GeoBusinessMetricEntry).where(
                GeoBusinessMetricEntry.workspace_id == workspace_id,
                GeoBusinessMetricEntry.import_batch_id == batch.id,
                GeoBusinessMetricEntry.reverses_entry_id.is_(None),
            )
        )
    )
    already_reversed = set(
        value for value in db.scalars(
            select(GeoBusinessMetricEntry.reverses_entry_id).where(
                GeoBusinessMetricEntry.reverses_entry_id.in_([row.id for row in entries] or [-1])
            )
        ) if value
    )
    for original in entries:
        if original.id in already_reversed:
            continue
        db.add(GeoBusinessMetricEntry(
            workspace_id=workspace_id,
            action_id=original.action_id,
            metric_type=original.metric_type,
            amount_minor=-original.amount_minor if original.amount_minor is not None else None,
            quantity=-original.quantity if original.quantity is not None else None,
            currency=original.currency,
            attribution_type=original.attribution_type,
            source_type="system",
            source_label=f"冲销导入批次 #{batch.id}",
            source_reference=original.source_reference,
            evidence_note=f"批量冲销原因：{payload.reason.strip()}",
            verification_status="system_verified",
            occurred_at=datetime.now(UTC),
            created_by_user_id=user.id,
            idempotency_key=f"csv-reversal:{batch.id}:{original.id}",
            reverses_entry_id=original.id,
            reversal_reason=payload.reason.strip(),
            import_batch_id=batch.id,
            source_record_id=original.source_record_id,
        ))
    batch.status = "reversed"
    batch.reversed_at = datetime.now(UTC)
    record_audit_log(
        db,
        user=user,
        action="geo.business_metric.csv_import_reversed",
        resource_type="geo_business_metric_import",
        resource_id=batch.id,
        company_id=workspace.company_id,
        detail={"workspace_id": workspace_id, "reason": payload.reason.strip()},
    )
    db.commit()
    db.refresh(batch)
    return batch_read(db, batch)
