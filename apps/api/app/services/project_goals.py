from app.models import ProjectStageGoal


def goal_suggested_actions(goal: ProjectStageGoal, risk_level: str) -> list[dict[str, str]]:
    if goal.status in {"completed", "archived"} or risk_level in {"completed", "archived"}:
        return []
    note = goal.note or ""
    suggestions: list[dict[str, str]] = []

    def add(action_type: str, label: str, reason: str, priority: str = "primary") -> None:
        if any(item["action_type"] == action_type for item in suggestions):
            return
        suggestions.append(
            {
                "action_type": action_type,
                "label": label,
                "reason": reason,
                "priority": priority,
            }
        )

    if "report_delivery_readiness_id=" in note:
        if "真实模型样本" in note or "真实大模型 API" in note:
            add("run_real_provider_smoke", "跑真实模型小样本", "该报告缺少真实大模型样本，先用已测通真实 Provider 跑 1 个目标问题小样本。")
            add("run_crawl", "补采 API 样本", "真实小样本通过后，再扩大到更多目标问题和关键词。", "secondary")
        else:
            add("run_crawl", "补采证据", "交付就绪度存在阻塞项，优先补齐样本、模型覆盖或证据链。")
        add("generate_draft", "补内容并评分", "交付质量整改通常需要内容资产支撑报告建议。", "secondary")
        add("create_delivery_followup", "创建交付跟进", "质量整改目标需要负责人持续跟进。", "secondary")
        return suggestions

    if "report_observation_id=" in note or goal.metric_key == "browser_observation_count":
        add("open_browser_observation", "录入网页观测", "该目标要求补充网页端搜索留证。")
        add("run_crawl", "同步补采 API 样本", "网页端观测建议和 API 采集样本交叉校验。", "secondary")
        return suggestions

    if goal.metric_key == "answer_count":
        add("run_crawl", "发起采集", "该目标的核心缺口是 AI 答案样本不足。")
    elif goal.metric_key == "approved_content_count":
        add("generate_draft", "生成并评分", "该目标需要增加可审核通过的 GEO 内容。")
    elif goal.metric_key == "published_placement_count":
        add("create_placement", "创建投放", "该目标需要把已通过内容推进到投放计划。")
    elif goal.metric_key == "accepted_delivery_count":
        add("create_delivery_followup", "交付跟进", "该目标需要客户确认和交付跟进。")
        add("publish_prepare_delivery", "发布交付", "如果已有阶段目标投放，先发布并进入客户交付包。", "secondary")
    elif goal.metric_key == "recommendation_rate":
        add("generate_draft", "补内容并评分", "推荐率目标通常需要更强的结构化内容和信源证据。")
        add("run_crawl", "复测推荐变化", "补内容前后需要采集样本验证推荐率。", "secondary")
    elif goal.metric_key == "maturity_score":
        add("run_crawl", "补采成熟度样本", "成熟度提升需要先补齐跨模型证据。")
        add("generate_draft", "生成优化内容", "用报告缺口驱动内容生产。", "secondary")
    else:
        add("run_full_loop", "一键闭环", "该目标可通过采集、撰稿、审核、投放和交付串联推进。")

    if risk_level in {"overdue", "at_risk"}:
        add("create_delivery_followup", "创建跟进提醒", "该目标存在进度风险，需要进入待办跟进。", "secondary")
    return suggestions
