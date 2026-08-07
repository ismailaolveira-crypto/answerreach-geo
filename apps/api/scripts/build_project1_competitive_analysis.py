from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "apps" / "api" / "geo_platform.db"
OUTPUT_PATH = ROOT / "docs" / "reports" / "project-1-report-6-competitive-analysis.md"
TASK_ID = 8
REPORT_ID = 6

COMPETITORS = {"阿里云百炼", "LiteLLM", "Portkey", "Langfuse", "OpenRouter", "Helicone"}

URL_CHECKS = {
    "https://apisix.apache.org/zh/": (200, "可访问；APISIX 官方站，但不是春秋元泉信源"),
    "https://aws.amazon.com/cn/bedrock/": (200, "可访问；AWS Bedrock 官方产品页"),
    "https://bailian.console.aliyun.com/": (200, "可访问；阿里云百炼控制台入口"),
    "https://cloud.tencent.com/document/product/851/105263": (200, "可访问；腾讯云官方文档"),
    "https://cloud.tencent.com/product/ti": (200, "可访问；腾讯云官方产品页"),
    "https://cloud.tencent.com/product/tione": (200, "可访问；腾讯云官方产品页"),
    "https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html": (200, "可访问；AWS 官方文档"),
    "https://docs.mulesoft.com/ai-gateway/latest/": (404, "原链接失效"),
    "https://help.aliyun.com/document_detail/2587912.html": (200, "可访问但已跳转到 PAI 实验页面，和回答声称的百炼网关证据不完全匹配"),
    "https://konghq.com/products/api-gateway/ai-gateway": (404, "原链接失效；当前官方 AI Gateway 页面路径已变化"),
    "https://konghq.com/solutions/ai-gateway": (404, "原链接失效；当前官方 AI Gateway 页面路径已变化"),
    "https://learn.microsoft.com/zh-cn/azure/api-management/api-management-llm-gateway": (404, "原链接失效；微软现行文档路径已变化"),
    "https://openai.justsong.cn/": (0, "本次网络核验不可达，且不是官方厂商域名"),
    "https://support.huaweicloud.com/productdesc-modelarts/modelarts_01_0001.html": (200, "可访问；华为云官方产品说明"),
    "https://www.apiseven.com/": (200, "可访问；商业公司站点"),
    "https://www.apisix.cn/products/apisix-llm-gateway": (0, "本次网络核验不可达"),
    "https://www.huaweicloud.com/product/modelarts.html": (200, "可访问；华为云官方产品页"),
    "https://www.mulesoft.com/platform/ai-gateway": (403, "站点拒绝自动访问，未完成内容核验"),
    "https://www.one-ai.com/": (0, "本次网络核验不可达"),
    "https://www.volcengine.com/product/ark": (200, "可访问；火山方舟官方产品页"),
}

OBSERVATION_PLANS = [
    (16, "P0", "产品核心能力是17次提及的最大来源，需验证网页端是否复述同一组能力以及是否出现无依据参数。"),
    (17, "P0", "4/4 API回答均因缺乏权威公开资料而拒答，最能检验公开内容缺口。"),
    (18, "P0", "4/4均提及春秋元泉并与LiteLLM比较，需核对网页端是否给出相同定位。"),
    (19, "P0", "包含唯一一次明确推荐春秋元泉的样本，必须截图复核推荐是否可重复。"),
    (20, "P0", "API回答多数拒绝比较Langfuse，适合验证补充公开材料后的变化。"),
    (1, "P1", "自然需求问题，用于验证没有品牌词时能否进入候选名单。"),
    (6, "P1", "竞品与网址线索最集中的问题，可对照网页端真实信源卡片。"),
    (7, "P1", "企业治理选型问题，检验春秋元泉能否与云厂商和开源产品同台出现。"),
    (23, "P1", "配额与成本分摊是竞品推荐高发场景。"),
    (24, "P1", "密钥、审计、成本治理三合一，是产品价值主张的核心自然问题。"),
]

ARTICLE_PLANS = [
    {
        "priority": "P0",
        "platform": "春秋元泉官网产品页 + 官方文档中心",
        "title": "春秋元泉 Token 统一管控平台：核心能力、适用边界与部署方式",
        "target_questions": [16, 17],
        "basis": "问题16有4次提及但能力描述缺少可核验出处；问题17有4次拒答。",
        "must_include": "真实功能清单、支持的模型/协议、部署形态、适用企业、限制条件、更新时间；所有参数须经产品负责人确认。",
    },
    {
        "priority": "P0",
        "platform": "春秋元泉官网解决方案页",
        "title": "企业如何统一管理多模型 API 密钥、配额、审计与 Token 成本",
        "target_questions": [1, 2, 4, 13, 23, 24],
        "basis": "这些自然问题由阿里云百炼、LiteLLM、Portkey等占位，春秋元泉未进入自然推荐。",
        "must_include": "架构图、角色与权限、成本归因口径、告警/审计流程、可验证产品截图。",
    },
    {
        "priority": "P0",
        "platform": "春秋元泉官网对比中心",
        "title": "春秋元泉与 LiteLLM：企业治理平台和开源统一调用层如何选择",
        "target_questions": [18],
        "basis": "4/4样本提及双方，但模型自行补全了大量未经春秋元泉官方材料证明的能力。",
        "must_include": "定位、部署、权限、审计、成本、运维责任、适用团队；引用LiteLLM官方文档并标注核验日期。",
    },
    {
        "priority": "P0",
        "platform": "春秋元泉官网对比中心 + 知乎机构号",
        "title": "春秋元泉与 Portkey 怎么选：国内企业治理和 AI Gateway 的关键差异",
        "target_questions": [19],
        "basis": "唯一一次春秋元泉推荐发生在该问题，但其他样本反复指出公开资料不足。",
        "must_include": "可复核的功能矩阵、部署与合规边界、适用/不适用场景；不得使用无法证明的优劣结论。",
    },
    {
        "priority": "P0",
        "platform": "春秋元泉官网对比中心 + CSDN/掘金技术专栏",
        "title": "春秋元泉与 Langfuse：Token治理、LLM可观测与成本归因的边界",
        "target_questions": [20],
        "basis": "2次春秋元泉提及均暴露公开资料不足，且模型会把Helicone、LangSmith等带入候选。",
        "must_include": "链路追踪、调用日志、成本、密钥、权限、私有化的真实差异和集成示例。",
    },
    {
        "priority": "P1",
        "platform": "微信公众号",
        "title": "从多模型接入到成本分摊：企业大模型治理落地清单",
        "target_questions": [3, 7, 13, 23, 24],
        "basis": "高意图采购问题中竞品高频出现，适合用管理者语言建立品类认知。",
        "must_include": "采购检查表、责任分工、上线步骤，并链接回官网的权威产品和文档页。",
    },
    {
        "priority": "P1",
        "platform": "知乎机构号",
        "title": "企业级大模型接入治理平台怎么选：云厂商、开源网关和统一管控平台",
        "target_questions": [6, 7, 23, 24],
        "basis": "阿里云百炼在采购问题中推荐次数最高；LiteLLM、Portkey在技术选型中持续占位。",
        "must_include": "中立分类、选择条件、公开信源链接和春秋元泉的适用边界，避免软文式绝对化表述。",
    },
    {
        "priority": "P1",
        "platform": "CSDN/掘金 + 可选GitHub真实示例仓库",
        "title": "多模型 API 统一接入、配额与成本归因的工程实现",
        "target_questions": [1, 2, 4, 13, 23, 24],
        "basis": "LiteLLM和Portkey主要在工程实现类问题中获得提及与推荐。",
        "must_include": "可运行配置、API示例、日志字段和指标定义；只有真实可维护代码才发布GitHub。",
    },
]


def clean_text(value: str | None, limit: int = 260) -> str:
    text = " ".join((value or "").replace("\\n", " ").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def normalize_url(url: str) -> str:
    return url.rstrip("）)")


def render_markdown(doc: dict) -> str:
    lines = [
        "# 春秋元泉 Token 统一管控平台 GEO 竞品分析说明文档",
        "",
        "## Executive Summary",
        "",
        "- **17次品牌提及高度集中。** 仅来自5个品牌词问题的17条回答，不代表自然采购问题中已有稳定可见度。",
        "- **唯一明确推荐不可外推。** 仅问题19的第3次样本把春秋元泉列为第1候选；其余16条只是提及，其中多条明确表示公开材料不足。",
        "- **竞品占位发生在自然高意图问题。** 阿里云百炼、LiteLLM和Portkey已在多模型接入、配额、密钥、审计和成本治理问题中获得推荐。",
        "- **信源缺口是当前首要问题。** 23条URL均来自问题6的API回答，没有一条直接证明春秋元泉能力；它们只能作为网址线索，不能证明模型真实检索过这些页面。",
        "",
        "## 口径与边界",
        "",
        f"- 数据范围：项目1，采集任务 #{doc['scope']['task_id']}，{doc['scope']['answer_count']}条真实大模型API回答。",
        "- 样本设计：25个问题，每题4次；本说明文档不使用历史任务、Mock或演示数据。",
        "- “提及/推荐”来自落库解析结果；“网页观测”必须由实际网页端搜索和截图另行回填。",
        "- API回答中出现的网址不等于真实检索信源；本次只核验网址当前是否可访问及是否与页面主题相符。",
        "",
        "## 春秋元泉17次提及逐条明细",
        "",
        "| 问题ID | 样本 | 结果ID | 状态 | 提及语境 |",
        "|---:|---:|---:|---|---|",
    ]
    for item in doc["company_mentions"]:
        status = f"推荐，第{item['rank']}位" if item["recommended"] else "仅提及"
        lines.append(
            f"| {item['question_id']} | {item['sample_run']} | {item['result_id']} | {status} | {item['context'].replace('|', '｜')} |"
        )
    lines.extend(["", "### 按问题汇总", "", "| 问题 | 提及样本 | 判断 |", "|---|---|---|"])
    for item in doc["company_question_summary"]:
        lines.append(
            f"| Q{item['question_id']} {item['question'].replace('|', '｜')} | {', '.join(map(str, item['sample_runs']))} | {item['interpretation']} |"
        )
    lines.extend([
        "",
        "## 网页端观测与截图补证清单",
        "",
        "每个问题分别在豆包、DeepSeek、Kimi、千问网页端执行一次自然提问；截图必须同时包含平台标识、完整问题、答案中的品牌/竞品段落、可见信源卡片和观测时间。",
        "",
        "| 优先级 | 问题 | 平台 | 当前状态 | 补证目的 |",
        "|---|---|---|---|---|",
    ])
    for item in doc["observation_plan"]:
        lines.append(
            f"| {item['priority']} | Q{item['question_id']} {item['question'].replace('|', '｜')} | {'、'.join(item['platforms'])} | {item['status']} | {item['reason']} |"
        )
    lines.extend(["", "## 竞品在哪些问题中被提及和推荐", ""])
    for competitor in doc["competitors"]:
        lines.extend([
            f"### {competitor['name']}",
            "",
            f"共出现在{competitor['answer_mentions']}条回答中，累计提及{competitor['mention_count']}次，获得{competitor['recommendation_count']}次推荐。",
            "",
            "| 问题 | 样本 | 提及次数 | 推荐位 | 回答中的网址线索 | 语境 |",
            "|---|---:|---:|---:|---|---|",
        ])
        for item in competitor["samples"]:
            lines.append(
                f"| Q{item['question_id']} {item['question'].replace('|', '｜')} | {item['sample_run']} | {item['mention_count']} | {item['rank'] or '-'} | {'<br>'.join(item['claimed_source_urls']) or '无'} | {item['context'].replace('|', '｜')} |"
            )
        lines.append("")
    lines.extend([
        "## 回答声称参考的网址线索",
        "",
        "23条网址记录全部来自Q6。下面的“可访问”仅表示2026年7月14日从当前环境访问成功，不证明模型生成答案时真实访问过该页面，也不构成春秋元泉产品证据。",
        "",
        f"- 带网址线索的回答：{doc['source_summary']['answers_with_claimed_urls']}/100",
        f"- 无网址线索的回答：{doc['source_summary']['answers_without_claimed_urls']}/100",
        f"- 已证明真实检索链路的回答：{doc['source_summary']['lineage_verified_count']}/100",
        "",
        "| 域名 | URL | 出现次数 | 当前核验 | 证据结论 |",
        "|---|---|---:|---|---|",
    ])
    for item in doc["source_leads"]:
        lines.append(
            f"| {item['domain']} | {item['url']} | {item['occurrences']} | {item['http_status'] or '不可达'} | {item['verification_note']} |"
        )
    lines.extend([
        "",
        "## 下一阶段内容发布建议",
        "",
        "先补官网权威证据，再做外部平台分发。官网产品页、文档、案例和FAQ应作为其他文章的统一引用源；第三方平台文章只承担解释和触达，不替代一手产品证据。",
        "",
        "| 优先级 | 推荐平台 | 文章选题 | 目标问题 | 证据依据 | 必备内容 |",
        "|---|---|---|---|---|---|",
    ])
    for item in doc["article_plan"]:
        lines.append(
            f"| {item['priority']} | {item['platform']} | {item['title']} | {', '.join('Q'+str(q) for q in item['target_questions'])} | {item['basis']} | {item['must_include']} |"
        )
    lines.extend([
        "",
        "## 推荐执行顺序",
        "",
        "1. 一周内补齐官网产品总览、适用企业、真实功能边界和三篇对比页，并由产品负责人完成事实校验。",
        "2. 对10个观测问题在4个网页端平台执行首轮截图，先验证当前基线，再发布内容。",
        "3. 发布后按周复测同一问题集，比较品牌自然提及、推荐率和可见信源卡片的变化。",
        "4. 微信、知乎、CSDN/掘金只分发已在官网有权威出处的内容；不编造客户案例、参数或第三方背书。",
        "",
        "## Further Questions",
        "",
        "- 春秋元泉是否已有可公开的产品说明、部署手册、真实客户案例和功能截图？",
        "- 哪些能力已经正式上线，哪些仍处于规划或定制交付状态？",
        "- 是否允许公开定价、支持模型清单、协议清单和性能指标？",
        "",
        "## Caveats and Assumptions",
        "",
        "- 本报告只分析任务#8的一家API模型渠道，不能代表所有模型或网页端搜索表现。",
        "- 实体推荐位由当前解析器生成；涉及外部发布前仍需人工复核原始回答。",
        "- 网址核验只检查当前可访问性和主题相关性，不证明答案的检索链路。",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    question_rows = conn.execute(
        "SELECT id, question_text FROM target_questions WHERE project_id=1"
    ).fetchall()
    questions = {int(row["id"]): row["question_text"] for row in question_rows}

    mention_rows = conn.execute(
        """
        SELECT cr.id result_id, cr.target_question_id question_id, tq.question_text,
               CAST(json_extract(ur.detail_json, '$.sample_run') AS INTEGER) sample_run,
               aa.company_recommended, aa.company_rank, me.context_excerpt
        FROM crawl_results cr
        JOIN target_questions tq ON tq.id=cr.target_question_id
        JOIN answer_analysis aa ON aa.crawl_result_id=cr.id AND aa.company_mentioned=1
        LEFT JOIN mentioned_entities me ON me.crawl_result_id=cr.id AND me.is_company=1
        LEFT JOIN usage_records ur ON ur.crawl_result_id=cr.id AND ur.task_id=?
        WHERE cr.task_id=? ORDER BY cr.target_question_id, sample_run
        """,
        (TASK_ID, TASK_ID),
    ).fetchall()
    company_mentions = [
        {
            "result_id": int(row["result_id"]),
            "question_id": int(row["question_id"]),
            "question": row["question_text"],
            "sample_run": int(row["sample_run"]),
            "recommended": bool(row["company_recommended"]),
            "rank": row["company_rank"],
            "context": clean_text(row["context_excerpt"]),
        }
        for row in mention_rows
    ]

    interpretations = {
        16: "4/4提及；回答主动补全了大量产品能力，但本任务没有春秋元泉官方信源支撑，需逐项事实核验。",
        17: "4/4提及但全部拒答；公开的适用企业、行业和部署边界明显不足。",
        18: "4/4提及；模型能完成与LiteLLM对比，但对春秋元泉的描述存在无来源推断风险。",
        19: "3/4提及；仅样本3明确推荐且排第1，另外样本强调公开资料不足。",
        20: "2/4提及；两条均表示缺少权威资料，另两条回答也未形成有效品牌推荐。",
    }
    by_question: dict[int, list[dict]] = defaultdict(list)
    for item in company_mentions:
        by_question[item["question_id"]].append(item)
    company_question_summary = [
        {
            "question_id": question_id,
            "question": questions[question_id],
            "sample_runs": [item["sample_run"] for item in items],
            "interpretation": interpretations[question_id],
        }
        for question_id, items in sorted(by_question.items())
    ]

    entity_rows = conn.execute(
        """
        SELECT me.entity_name, cr.id result_id, cr.target_question_id question_id,
               tq.question_text, CAST(json_extract(ur.detail_json, '$.sample_run') AS INTEGER) sample_run,
               me.mention_count, me.recommendation_rank, me.context_excerpt
        FROM mentioned_entities me
        JOIN crawl_results cr ON cr.id=me.crawl_result_id
        JOIN target_questions tq ON tq.id=cr.target_question_id
        LEFT JOIN usage_records ur ON ur.crawl_result_id=cr.id AND ur.task_id=?
        WHERE cr.task_id=? AND me.is_competitor=1
        ORDER BY me.entity_name, cr.target_question_id, sample_run
        """,
        (TASK_ID, TASK_ID),
    ).fetchall()
    grouped_entities: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in entity_rows:
        if row["entity_name"] in COMPETITORS:
            grouped_entities[row["entity_name"]].append(row)
    competitors = []
    for name, rows in grouped_entities.items():
        competitors.append(
            {
                "name": name,
                "answer_mentions": len(rows),
                "mention_count": sum(int(row["mention_count"] or 0) for row in rows),
                "recommendation_count": sum(1 for row in rows if row["recommendation_rank"] is not None),
                "samples": [
                    {
                        "result_id": int(row["result_id"]),
                        "question_id": int(row["question_id"]),
                        "question": row["question_text"],
                        "sample_run": int(row["sample_run"]),
                        "mention_count": int(row["mention_count"] or 0),
                        "rank": row["recommendation_rank"],
                        "context": clean_text(row["context_excerpt"], 220),
                    }
                    for row in rows
                ],
            }
        )
    competitors.sort(key=lambda item: (-item["recommendation_count"], -item["mention_count"], item["name"]))

    source_rows = conn.execute(
        """
        SELECT cs.source_url, cs.source_domain, COUNT(*) occurrences,
               GROUP_CONCAT(DISTINCT cr.target_question_id) question_ids
        FROM citation_sources cs JOIN crawl_results cr ON cr.id=cs.crawl_result_id
        WHERE cr.task_id=? GROUP BY cs.source_url, cs.source_domain
        ORDER BY cs.source_domain, cs.source_url
        """,
        (TASK_ID,),
    ).fetchall()
    merged_sources: dict[str, dict] = {}
    for row in source_rows:
        url = normalize_url(row["source_url"])
        if url not in merged_sources:
            status, note = URL_CHECKS.get(url, (0, "尚未完成当前网络核验"))
            merged_sources[url] = {
                "domain": row["source_domain"],
                "url": url,
                "occurrences": 0,
                "question_ids": set(),
                "http_status": status,
                "verification_note": note,
                "lineage_status": "API回答声称的网址线索；不是已证明的模型检索来源",
            }
        merged_sources[url]["occurrences"] += int(row["occurrences"])
        merged_sources[url]["question_ids"].update(int(value) for value in row["question_ids"].split(","))
    source_leads = []
    for item in merged_sources.values():
        item["question_ids"] = sorted(item["question_ids"])
        source_leads.append(item)
    source_result_rows = conn.execute(
        """
        SELECT cs.crawl_result_id, cs.source_url
        FROM citation_sources cs JOIN crawl_results cr ON cr.id=cs.crawl_result_id
        WHERE cr.task_id=? ORDER BY cs.crawl_result_id, cs.id
        """,
        (TASK_ID,),
    ).fetchall()
    sources_by_result: dict[int, list[str]] = defaultdict(list)
    for row in source_result_rows:
        url = normalize_url(row["source_url"])
        if url not in sources_by_result[int(row["crawl_result_id"])]:
            sources_by_result[int(row["crawl_result_id"])].append(url)
    for competitor in competitors:
        for sample in competitor["samples"]:
            sample["claimed_source_urls"] = sources_by_result.get(sample["result_id"], [])
    answers_with_claimed_urls = len(sources_by_result)

    observation_plan = [
        {
            "question_id": question_id,
            "question": questions[question_id],
            "priority": priority,
            "platforms": ["豆包", "DeepSeek", "Kimi", "千问"],
            "status": "待网页端人工观测与截图",
            "reason": reason,
            "required_evidence": ["平台标识", "完整问题", "答案品牌段落", "可见信源", "观测时间"],
        }
        for question_id, priority, reason in OBSERVATION_PLANS
    ]

    doc = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "project_id": 1,
            "report_id": REPORT_ID,
            "task_id": TASK_ID,
            "answer_count": 100,
            "question_count": 25,
            "samples_per_question": 4,
            "evidence_type": "真实大模型API回答；非网页端搜索存证",
        },
        "executive_findings": [
            "17次提及集中于5个品牌词问题；自然采购问题中未形成稳定可见度。",
            "唯一明确推荐发生在Q19样本3，排名第1。",
            "23条URL全部来自Q6，且没有春秋元泉官方信源。",
            "下一步应先建设官网权威证据，再做网页端观测和外部平台分发。",
        ],
        "company_mentions": company_mentions,
        "company_question_summary": company_question_summary,
        "observation_plan": observation_plan,
        "competitors": competitors,
        "source_leads": source_leads,
        "source_summary": {
            "record_count": sum(item["occurrences"] for item in source_leads),
            "unique_url_count": len(source_leads),
            "all_from_question_ids": sorted({q for item in source_leads for q in item["question_ids"]}),
            "company_official_source_count": 0,
            "lineage_verified_count": 0,
            "reachable_url_count": sum(1 for item in source_leads if item["http_status"] == 200),
            "answers_with_claimed_urls": answers_with_claimed_urls,
            "answers_without_claimed_urls": 100 - answers_with_claimed_urls,
        },
        "article_plan": ARTICLE_PLANS,
        "caveats": [
            "只覆盖任务#8的一家API模型渠道。",
            "网址可访问不等于模型生成时真实检索过该网址。",
            "所有春秋元泉产品能力、案例和参数在发布前必须由产品负责人确认。",
        ],
    }
    if len(company_mentions) != 17:
        raise RuntimeError(f"expected 17 company mention rows, got {len(company_mentions)}")
    if sum(item["recommendation_count"] for item in competitors) != 23:
        raise RuntimeError("competitor recommendation count no longer matches report #6")
    if doc["source_summary"]["record_count"] != 23:
        raise RuntimeError("source record count no longer matches report #6")
    doc["markdown"] = render_markdown(doc)

    report_row = conn.execute("SELECT report_json FROM maturity_reports WHERE id=?", (REPORT_ID,)).fetchone()
    if report_row is None:
        raise RuntimeError("report #6 not found")
    report_json = json.loads(report_row["report_json"])
    report_json["competitive_analysis_document"] = doc
    conn.execute(
        "UPDATE maturity_reports SET report_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(report_json, ensure_ascii=False), REPORT_ID),
    )
    conn.commit()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(doc["markdown"], encoding="utf-8")
    print(json.dumps({"report_id": REPORT_ID, "company_mentions": len(company_mentions), "competitors": len(competitors), "source_records": 23, "output": str(OUTPUT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
