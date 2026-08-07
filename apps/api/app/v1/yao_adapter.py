from urllib.parse import urlparse

from fastapi import HTTPException

from app.models.cleanroom_v1 import GeoWorkspace
from app.v1.schemas import YaoDatasetImport, YaoDeepSeekDatasetImport, YaoSampleImport, YaoSourceItem


def _artifact_uri(base_uri: str | None, relative_path: str | None) -> str | None:
    if not base_uri or not relative_path:
        return None
    return f"{base_uri.rstrip('/')}/{relative_path.lstrip('/')}"


def _brand_status(workspace: GeoWorkspace, answer: str, references: list[YaoSourceItem]) -> str:
    names = [workspace.brand_name, *workspace.brand_aliases]
    mentioned = any(name and name.lower() in answer.lower() for name in names)
    brand_host = urlparse(workspace.website_url or "").netloc.lower()
    cited = brand_host and any(brand_host in (urlparse(item.url or "").netloc.lower()) for item in references)
    if cited:
        return "cited"
    return "mentioned" if mentioned else "absent"


def normalize_yao_stage1_dataset(
    workspace: GeoWorkspace,
    payload: YaoDeepSeekDatasetImport,
    platform: str,
    schema_prefix: str,
) -> YaoDatasetImport:
    dataset = payload.dataset
    schema_version = str(dataset.get("schema_version", ""))
    if not schema_version.startswith(schema_prefix):
        raise HTTPException(status_code=422, detail=f"Expected a {schema_prefix} stage-1 dataset")
    rows = dataset.get("samples")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=422, detail="Yao dataset has no samples")
    samples: list[YaoSampleImport] = []
    for row in rows:
        result = row.get("result") or {}
        answer = (result.get("answer") or {}).get("text") or ""
        references = [YaoSourceItem.model_validate(item) for item in (result.get("references") or {}).get("items", [])]
        artifacts = result.get("artifacts") or {}
        screenshots = artifacts.get("screenshots") or []
        samples.append(
            YaoSampleImport(
                sample_id=str(row.get("sample_id", "")),
                question=str(row.get("question") or result.get("question") or ""),
                repeat_index=int(row.get("repeat_index") or 1),
                ok=bool(row.get("ok")),
                started_at=row.get("started_at"),
                finished_at=row.get("finished_at") or result.get("collected_at"),
                raw_artifact_uri=_artifact_uri(payload.artifact_base_uri, row.get("raw_path")),
                screenshot_uri=_artifact_uri(payload.artifact_base_uri, screenshots[0] if screenshots else None),
                sampling_environment={
                    "source_schema": schema_version,
                    "run_id": (dataset.get("run") or {}).get("id"),
                    "transport": result.get("transport") or (dataset.get("run") or {}).get("transport"),
                    "search_enabled": (result.get("options") or {}).get("search"),
                },
                answer_text=answer,
                references=references,
                brand_status=_brand_status(workspace, answer, references),
            )
        )
    return YaoDatasetImport(
        platform=platform,
        sample_mode="browser_assisted",
        evidence_level="auditable" if payload.artifact_base_uri else "partial",
        prompt_version=payload.prompt_version,
        browser_account_id=payload.browser_account_id,
        lease_token=payload.lease_token,
        samples=samples,
    )
