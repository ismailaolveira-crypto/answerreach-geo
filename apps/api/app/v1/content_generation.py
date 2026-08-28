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
    "juejin": {
        "label": "稀土掘金",
        "tone": "开发者视角、实践导向；讲清实现过程、工程取舍和踩坑，不写成产品宣传稿。",
        "format": "Markdown 技术文章，使用清晰 H2、步骤、异常路径；代码或配置只在有真实输入时使用。",
        "required": ["工程问题", "实现思路", "关键取舍", "适用边界", "来源链接"],
    },
    "csdn": {
        "label": "CSDN",
        "tone": "可执行、可复现、先结论后步骤；保留必要前置条件，避免硬广和营销链接堆叠。",
        "format": "Markdown 教程，明确输入、输出、操作步骤、异常路径和验证方法。",
        "required": ["问题结论", "前置条件", "执行步骤", "异常处理", "来源链接"],
    },
    "51cto": {
        "label": "51CTO",
        "tone": "面向企业 IT 与运维读者，稳健、清单化；强调治理责任、实施边界与复盘。",
        "format": "企业技术实践文章，使用治理清单、角色边界、落地步骤和风险说明。",
        "required": ["治理问题", "责任边界", "实施清单", "风险提示", "来源链接"],
    },
    "wechat": {
        "label": "微信公众号",
        "tone": "面向业务读者，简洁有节奏；标题具体，段落短，避免把研究报告原样搬运。",
        "format": "适合移动端阅读，短段落、小标题、要点列表和结尾行动建议。",
        "required": ["场景引入", "核心观点", "案例/证据", "读者下一步"],
    },
    "bilibili": {
        "label": "哔哩哔哩专栏",
        "tone": "年轻但不轻浮，概念解释直白；让读者快速理解问题和实际做法。",
        "format": "专栏文章，短段落、小标题、重点清单和可核验来源。",
        "required": ["问题背景", "通俗解释", "操作要点", "来源链接"],
    },
    "baijiahao": {
        "label": "百家号",
        "tone": "资讯化、清楚、客观；标题准确，不制造悬念或夸大效果。",
        "format": "资讯型文章，首段交代结论，正文分点说明依据与影响。",
        "required": ["核心结论", "事实依据", "影响分析", "来源链接"],
    },
    "weibo": {
        "label": "微博头条文章",
        "tone": "简短直接、适合社交传播；不使用未经证实的热点判断。",
        "format": "头条文章，开头给结论，段落短，重点可快速扫读。",
        "required": ["一句话结论", "关键要点", "证据来源", "讨论问题"],
    },
    "yuque": {
        "label": "语雀",
        "tone": "知识库式、结构严谨；方便团队复用、维护和追溯。",
        "format": "结构化文档，含摘要、目录式分节、步骤、边界和来源。",
        "required": ["文档摘要", "操作步骤", "适用边界", "来源链接"],
    },
    "douban": {
        "label": "豆瓣日记",
        "tone": "个人化但克制，重视真实体验和独立判断；避免营销腔。",
        "format": "日记体长文，以自然段和小标题组织观点、证据与反思。",
        "required": ["真实场景", "个人判断", "证据或出处", "局限说明"],
    },
    "sohu": {
        "label": "搜狐号",
        "tone": "媒体化、信息明确；避免标题党和无法验证的趋势预测。",
        "format": "媒体文章，导语概括结论，正文按信息层级展开。",
        "required": ["导语", "核心事实", "解释分析", "来源链接"],
    },
    "xueqiu": {
        "label": "雪球",
        "tone": "理性、数据优先、明确风险；不构成投资建议，不承诺收益。",
        "format": "观点文章，区分事实、推断和风险，列出数据口径与来源。",
        "required": ["观点结论", "数据依据", "风险提示", "来源链接"],
    },
    "cnblogs": {
        "label": "博客园",
        "tone": "工程实践导向、可复现；讲清环境、步骤、问题和验证。",
        "format": "Markdown 技术博客，包含前置条件、实现、异常和验证。",
        "required": ["前置条件", "实现步骤", "问题处理", "验证结果"],
    },
    "oschina": {
        "label": "开源中国",
        "tone": "面向开发与开源读者，重视实现细节、边界和可复用性。",
        "format": "技术文章，说明场景、方案、取舍、验证和参考资料。",
        "required": ["技术场景", "方案说明", "关键取舍", "来源链接"],
    },
    "segmentfault": {
        "label": "思否",
        "tone": "问题驱动、回答清晰；先解决核心问题，再补背景和边界。",
        "format": "问答式技术文章，包含问题、结论、步骤、验证和限制。",
        "required": ["问题定义", "直接结论", "实现步骤", "适用边界"],
    },
    "imooc": {
        "label": "慕课手记",
        "tone": "教学式、循序渐进；默认读者需要清晰的上下文和验证方法。",
        "format": "学习笔记，按目标、准备、步骤、结果和复盘组织。",
        "required": ["学习目标", "前置准备", "实践步骤", "结果验证"],
    },
    "woshipm": {
        "label": "人人都是产品经理",
        "tone": "产品与业务视角，强调用户问题、决策依据和落地效果。",
        "format": "产品案例文章，按问题、洞察、方案、执行与复盘展开。",
        "required": ["用户问题", "判断依据", "解决方案", "复盘边界"],
    },
    "eastmoney": {
        "label": "东方财富号",
        "tone": "财经表达稳健、数据口径清晰；不作收益承诺，不构成投资建议。",
        "format": "财经观点文章，区分事实与判断，标明数据时间和风险。",
        "required": ["核心判断", "数据口径", "风险提示", "来源链接"],
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
