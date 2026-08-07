import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Company
from app.services.answer_parser import _visibility_signals


def main() -> None:
    company = Company(name="春秋元泉", industry="大模型 API 治理", brand_aliases=[])
    cases = [
        {
            "name": "negative_natural_mention",
            "text": "是否自然会提到春秋元泉：不会。因为缺少公开信号、客户案例和第三方评测。",
            "mentioned": False,
            "recommended": False,
        },
        {
            "name": "negative_recommendation",
            "text": "目前不建议推荐春秋元泉，主要原因是公开信息不足，未经验证。",
            "mentioned": False,
            "recommended": False,
        },
        {
            "name": "positive_candidate",
            "text": "在 Token 统一管控平台选型中，春秋元泉可以作为候选之一，建议结合案例进一步评估。",
            "mentioned": True,
            "recommended": True,
        },
    ]
    results = []
    for case in cases:
        signals = _visibility_signals(case["text"], company)
        ok = (
            bool(signals["company_mentioned"]) is case["mentioned"]
            and bool(signals["company_recommended"]) is case["recommended"]
        )
        results.append({"case": case["name"], "ok": ok, "signals": signals})
    output = {"ok": all(item["ok"] for item in results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not output["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
