import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(__file__).resolve().parents[3] / "outputs" / "yuanquan_browser_observation_q1_template.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "outputs" / "yuanquan_browser_observation_q1_work_order.md"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _slug(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized.strip("-") or "observation"


def export_work_order(*, input_path: Path, output_path: Path) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    observations = payload.get("observations") if isinstance(payload, dict) else payload
    _require(isinstance(observations, list) and observations, "Template must contain observations")
    project = payload.get("project") if isinstance(payload, dict) else {}
    project_name = project.get("name") if isinstance(project, dict) else "GEO 项目"
    evidence_dir = input_path.parent / "raw-evidence"

    lines = [
        f"# {project_name} 网页端 GEO 采集工单",
        "",
        "## 执行目标",
        "",
        "在外部浏览器分别打开豆包、DeepSeek、Kimi、千问网页端，使用同一目标问题提问，复制完整答案，保存截图或录屏，并把结果填回 JSON 模板。",
        "",
        "## 填写规则",
        "",
        "- `raw_answer`：粘贴网页端返回的完整答案，不要只写摘要。",
        "- `answer_summary`：用一句话概括该平台回答。",
        "- `source_urls`：填页面可见信源 URL；如果没有可见信源，填 `[]`。",
        "- `evidence_filename`：推荐填写截图/录屏文件名，并把文件统一放到证据目录。",
        "- `screenshot_url`：如果不用证据目录，可填本地 `file://` 路径、对象存储地址或共享链接。",
        "- 保留 `platform_name`、`provider_id`、`target_question_id`、`prompt_text` 不变。",
        "",
        "## 采集任务",
        "",
    ]
    for index, item in enumerate(observations, start=1):
        platform = str(item.get("platform_name") or "未知平台")
        prompt_text = str(item.get("prompt_text") or "")
        observation_url = str(item.get("observation_url") or "")
        question_id = item.get("target_question_id")
        screenshot_name = str(item.get("evidence_filename") or f"{index:02d}-{_slug(platform)}-q{question_id or 'keyword'}.png")
        lines.extend(
            [
                f"### {index}. {platform}",
                "",
                f"- 网页入口：{observation_url}",
                f"- 目标问题：{prompt_text}",
                f"- 截图文件名：`{screenshot_name}`",
                "- 操作步骤：",
                "  1. 打开网页入口。",
                "  2. 复制目标问题并提问。",
                "  3. 等待答案完整生成。",
                "  4. 复制完整答案到 JSON 的 `raw_answer`。",
                "  5. 截图或录屏，文件名保持为 JSON 中的 `evidence_filename`；如使用外部链接，则填入 `screenshot_url`。",
                "  6. 如果页面展示来源，把 URL 填入 `source_urls`。",
                "",
            ]
        )
    lines.extend(
        [
            "## 导入前校验",
            "",
            "填完 JSON 后先执行 dry-run，不写入数据库：",
            "",
            "```bash",
            "UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/import_browser_observations.py \\",
            "  --project-id 1 \\",
            f"  --input {input_path} \\",
            f"  --evidence-dir {evidence_dir} \\",
            "  --dry-run",
            "```",
            "",
            "## 正式导入",
            "",
            "dry-run 通过后执行：",
            "",
            "```bash",
            "UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/import_browser_observations.py \\",
            "  --project-id 1 \\",
            f"  --input {input_path} \\",
            f"  --evidence-dir {evidence_dir} \\",
            "  --generate-draft",
            "```",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "ok": True,
        "input": str(input_path),
        "output": str(output_path),
        "observation_count": len(observations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a human-readable browser observation work order.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = export_work_order(input_path=args.input, output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
