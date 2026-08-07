import json

import httpx

from app.v1.competitor_insight import generate_competitor_insight


def test_competitor_insight_uses_selected_scope_and_keeps_only_known_evidence_ids() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "scope_summary": "全部问题范围共 3 条真实回答。",
                                    "overall_assessment": "当前范围只发现有限的对比信号。",
                                    "findings": [
                                        {
                                            "title": "竞品存在单条信号",
                                            "detail": "该信号需要回看对应原回答。",
                                            "evidence_ids": [41, 999],
                                        }
                                    ],
                                    "recommended_actions": ["补齐当前范围内问题的可引用产品材料。"],
                                    "limitations": ["样本量较小。"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    comparison = {
        "summary": {"answer_count": 3},
        "brands": [
            {
                "canonical_name": "春秋元泉",
                "is_baseline": True,
                "hit_answer_count": 1,
                "sample_answer_count": 3,
                "mention_rate": 33.3,
                "candidate_count": 0,
                "recommendation_count": 0,
                "explicit_average_position": None,
                "wins_over_baseline": 0,
                "comparable_answers": 0,
                "win_evidence": [],
                "evidence": [],
            },
            {
                "canonical_name": "阿里云 AI网关",
                "is_baseline": False,
                "hit_answer_count": 1,
                "sample_answer_count": 3,
                "mention_rate": 33.3,
                "candidate_count": 1,
                "recommendation_count": 0,
                "explicit_average_position": 1,
                "wins_over_baseline": 1,
                "comparable_answers": 1,
                "win_evidence": [
                    {
                        "evidence_id": 41,
                        "question": "如何统一管理密钥？",
                        "model_label": "DeepSeek",
                        "brand_name": "阿里云 AI网关",
                        "win_reason_type": "selected_baseline_absent",
                        "context_snippet": "阿里云 AI网关被列入候选。",
                    }
                ],
                "evidence": [],
            },
        ],
        "by_question": [{"label": "如何统一管理密钥？", "answer_count": 3}],
        "action_diagnostics": [
            {
                "competitor_key": "aliyun",
                "competitor_name": "阿里云 AI网关",
                "wins_over_baseline": 1,
                "question_plan_id": 4,
                "model_key": "deepseek",
                "question": "如何统一管理密钥？",
            }
        ],
    }

    result = generate_competitor_insight(
        comparison,
        api_key="test-key",
        selected_question_id=None,
        selected_question_label="全部已选问题",
        selected_model_label="全部已测模型",
        selected_period_label="近 90 天",
        transport=httpx.MockTransport(handler),
    )

    prompt = captured["messages"][1]["content"]
    assert "全部问题" in prompt
    assert result["analysis"]["findings"][0]["evidence_ids"] == [41]
    assert result["scope"]["kind"] == "全部问题"
