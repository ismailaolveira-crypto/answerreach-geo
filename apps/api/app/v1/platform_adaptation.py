"""Deterministic platform-tone adaptation without claiming external publication."""

from __future__ import annotations

from hashlib import sha256

from app.models.cleanroom_v1 import GeoContentAsset, GeoPlatformVariant
from app.v1.content_generation import PLATFORM_CONTRACTS

PLATFORM_SECTION_HEADINGS = {
    "zhihu": "先说结论",
    "juejin": "工程问题与实现取舍",
    "csdn": "问题、前置条件与执行步骤",
    "51cto": "企业 IT 治理清单",
    "bilibili": "先用大白话讲清楚",
    "baijiahao": "核心事实与影响",
    "weibo": "先看结论",
    "yuque": "文档摘要与操作步骤",
    "douban": "从真实场景说起",
    "sohu": "核心信息",
    "xueqiu": "判断、数据与风险",
    "cnblogs": "环境、实现与验证",
    "oschina": "技术方案与关键取舍",
    "segmentfault": "问题与直接答案",
    "imooc": "学习目标与实践步骤",
    "woshipm": "用户问题、方案与复盘",
    "eastmoney": "核心判断、数据与风险",
}


def adapt_asset(asset: GeoContentAsset, *, workspace_id: int, platform_key: str) -> GeoPlatformVariant:
    contract = PLATFORM_CONTRACTS.get(platform_key)
    if contract is None:
        raise ValueError(f"Unsupported platform contract: {platform_key}")
    label = str(contract["label"])
    source_body = asset.body_markdown.strip()
    if platform_key in PLATFORM_SECTION_HEADINGS:
        body = f"## {PLATFORM_SECTION_HEADINGS[platform_key]}\n\n{source_body}"
    elif platform_key == "wechat":
        body = f"{source_body}\n\n> 本文依据已归档的真实观测与公开来源整理。"
    elif platform_key == "xiaohongshu":
        body = f"{source_body}\n\n**来源说明**：仅使用 Brief 中已验证的来源，具体边界以原文为准。"
    else:
        body = source_body
    fingerprint = sha256(f"{asset.content_fingerprint}:{platform_key}:{body}".encode("utf-8")).hexdigest()
    return GeoPlatformVariant(
        workspace_id=workspace_id,
        content_asset_id=asset.id,
        platform_key=platform_key,
        version=1,
        policy_version="platform.v1",
        title=asset.title,
        summary=asset.summary,
        body_markdown=body,
        tags=[],
        category=None,
        image_manifest=[],
        adaptation_contract={
            "label": label,
            "tone": contract["tone"],
            "format": contract["format"],
            "required": contract["required"],
            "method": "deterministic_wrapper_pending_model_review",
        },
        content_fingerprint=fingerprint,
        prompt_hash=asset.prompt_hash,
        status="ready",
    )
