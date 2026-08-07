"""Content generation and platform adaptation primitives.

Provider calls are made only by an explicitly queued job. This module never
stores credentials and never marks an asset as verified without a later review.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Competitor, LLMProvider, Project
from app.models.cleanroom_v1 import GeoContentAsset, GeoContentBrief, GeoContentClaim, GeoWorkspace
from app.services.llm_provider import get_search_provider


ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "private_artifacts" / "content_generation"

PLATFORM_CONTRACTS: dict[str, dict[str, object]] = {
    "official_site": {
        "label": "官网",
        "tone": "专业、完整、可被检索；清晰回答问题并给出方法与证据，不使用夸张营销口号。",
        "format": "长文，使用清晰 H2/H3、定义、步骤、证据和 FAQ。",
        "required": ["首段直接回答问题", "来源链接", "适用边界", "行动建议"],
    },
    "zhihu": {
        "label": "知乎",
        "tone": "解释型、克制、先结论后论证；承认不确定性，避免硬广和堆砌关键词。",
        "format": "用自然问答结构，保留较强的经验解释和可核验引用。",
        "required": ["一句话结论", "判断依据", "反例或边界", "来源链接"],
    },
    "wechat": {
        "label": "微信公众号",
        "tone": "面向业务读者，简洁有节奏；标题具体，段落短，避免把研究报告原样搬运。",
        "format": "适合移动端阅读，短段落、小标题、要点列表和结尾行动建议。",
        "required": ["场景引入", "核心观点", "案例/证据", "读者下一步"],
    },
    "xiaohongshu": {
        "label": "小红书",
        "tone": "真实、具体、可执行；避免绝对化承诺、医疗/金融式保证和隐性广告。",
        "format": "短段落、清单化表达；正文和标题分别适配移动端发现流。",
        "required": ["具体场景", "可执行清单", "风险提示", "来源说明"],
    },
}


def _fingerprint(payload: object) -> str:
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_generation_prompt(
    workspace: GeoWorkspace,
    brief: GeoContentBrief,
    *,
    platform_key: str = "official_site",
) -> str:
    contract = PLATFORM_CONTRACTS.get(platform_key, PLATFORM_CONTRACTS["official_site"])
    sources = "\n".join(f"- {url}" for url in (brief.source_urls or [])) or "- 暂无来源；不得补写未验证事实"
    sections = "、".join(brief.required_sections or [])
    claims = "\n".join(f"- {claim}" for claim in (brief.required_claims or []))
    forbidden = "、".join(brief.forbidden_claims or []) or "无额外禁用词"
    return f"""你是春秋元泉 GEO 内容编辑。请根据已验证的观测 Brief 生成一份待人工审核的草稿。

品牌：{workspace.brand_name}
目标受众：{brief.audience}
用户意图：{brief.intent}
目标平台：{contract['label']}
平台调性：{contract['tone']}
平台格式：{contract['format']}
必须包含：{', '.join(str(item) for item in contract['required'])}
文章结构：{sections}
必须回答的主张：
{claims}
禁止声称：{forbidden}
已采集来源（只能引用这些 URL，不得虚构）：
{sources}

输出 Markdown，第一行是标题，随后是摘要和正文。不要输出分析过程，不要把未验证事实写成确定结论；若证据不足，明确标注“待补证据”。"""


def _company_project(db: Session, workspace: GeoWorkspace) -> tuple[Company, Project | SimpleNamespace, list[Competitor]]:
    company = db.get(Company, workspace.company_id)
    if company is None:
        raise ValueError("Workspace company not found")
    project = db.scalar(select(Project).where(Project.company_id == company.id).order_by(Project.id.desc()))
    if project is None:
        project = SimpleNamespace(
            name=f"{workspace.brand_name} GEO 内容生成",
            description="",
            target_industry=company.industry or "",
            target_audience="",
        )
        return company, project, []
    competitors = list(db.scalars(select(Competitor).where(Competitor.project_id == project.id)))
    return company, project, competitors


def generate_content_asset(
    db: Session,
    workspace: GeoWorkspace,
    brief: GeoContentBrief,
    provider: LLMProvider,
    *,
    platform_key: str = "official_site",
) -> GeoContentAsset:
    if provider.status != "active":
        raise ValueError("Selected content provider is not active")
    if provider.provider_type == "mock":
        raise ValueError("Mock providers cannot create a real content draft")
    company, project, competitors = _company_project(db, workspace)
    prompt = build_generation_prompt(workspace, brief, platform_key=platform_key)
    answer = get_search_provider(provider).answer(prompt, company, project, competitors)
    raw = {
        "provider_id": provider.id,
        "provider_type": provider.provider_type,
        "model_name": provider.model_name,
        "platform_key": platform_key,
        "prompt": prompt,
        "raw_answer": answer.raw_answer,
        "source_items": answer.source_items,
        "search_verified": answer.search_verified,
    }
    artifact_dir = ARTIFACT_ROOT / str(workspace.id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint({"brief": brief.input_fingerprint, "provider": provider.id, "platform": platform_key, "answer": answer.raw_answer})
    artifact_path = artifact_dir / f"brief-{brief.id}-{fingerprint}.json"
    artifact_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [line.strip() for line in answer.raw_answer.splitlines() if line.strip()]
    title = lines[0].lstrip("# ")[:255] if lines else brief.required_claims[0][:255]
    body = answer.raw_answer.strip()
    summary = next((line for line in lines[1:] if len(line) > 30), body[:240])
    asset = GeoContentAsset(
        workspace_id=workspace.id,
        brief_id=brief.id,
        version=1,
        title=title,
        summary=summary,
        body_markdown=body,
        content_fingerprint=fingerprint,
        model_provider_id=provider.id,
        model_name=provider.model_name,
        prompt_hash=_fingerprint(prompt),
        raw_artifact_uri=str(artifact_path),
        generation_usage={"search_verified": answer.search_verified, "source_count": len(answer.source_items)},
        status="draft",
    )
    db.add(asset)
    db.flush()
    for index, claim in enumerate(brief.required_claims or []):
        db.add(
            GeoContentClaim(
                content_asset_id=asset.id,
                claim_key=f"required-{index + 1}",
                claim_text=claim,
                support_type="brief_evidence",
                support_id=brief.evidence_ids[index] if index < len(brief.evidence_ids) else None,
                source_url=brief.source_urls[index] if index < len(brief.source_urls) else None,
                verification_status="pending",
                introduced_by_model=False,
            )
        )
    return asset
