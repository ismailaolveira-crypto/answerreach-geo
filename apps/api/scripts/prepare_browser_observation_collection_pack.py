import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_browser_observation_template import export_browser_observation_template
from export_browser_observation_work_order import export_work_order


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "outputs" / "yuanquan_browser_observation_pack_q1"


def _require(condition: bool, message: str, detail: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")


def _command_lines(*, project_id: int, template_path: Path, evidence_dir: Path, generate_draft: bool) -> list[str]:
    command = [
        "UV_CACHE_DIR=.uv-cache",
        "uv --directory apps/api run python scripts/import_browser_observations.py",
        f"--project-id {project_id}",
        f"--input {template_path}",
        f"--evidence-dir {evidence_dir}",
    ]
    command.append("--generate-draft" if generate_draft else "--dry-run")
    if generate_draft:
        command.extend(["--prepare-next-pack", f"--next-pack-output-dir {template_path.parent}"])
    return [" ".join(command)]


def prepare_collection_pack(
    *,
    project_id: int,
    output_dir: Path,
    question_limit: int,
    keyword_limit: int,
    platforms: list[str],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = output_dir / "raw-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    template_path = output_dir / "observations.json"
    work_order_path = output_dir / "work-order.md"
    dry_run_path = output_dir / "dry-run.sh"
    import_path = output_dir / "import-and-generate.sh"
    inspect_path = output_dir / "inspect.sh"
    readme_path = output_dir / "README.md"

    template_result = export_browser_observation_template(
        project_id=project_id,
        output_path=template_path,
        question_limit=question_limit,
        keyword_limit=keyword_limit,
        platforms=platforms,
    )
    work_order_result = export_work_order(input_path=template_path, output_path=work_order_path)
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    observations = payload.get("observations") if isinstance(payload, dict) else []
    _require(isinstance(observations, list) and observations, "Template did not create observations")
    evidence_filenames = [str(item.get("evidence_filename") or "").strip() for item in observations]
    evidence_filenames = [item for item in evidence_filenames if item]

    dry_run_command = _command_lines(
        project_id=project_id,
        template_path=template_path,
        evidence_dir=evidence_dir,
        generate_draft=False,
    )
    import_command = _command_lines(
        project_id=project_id,
        template_path=template_path,
        evidence_dir=evidence_dir,
        generate_draft=True,
    )
    inspect_command = [
        "UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/inspect_browser_observation_collection_pack.py "
        f"--pack-dir {output_dir}"
    ]
    inspect_path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + inspect_command[0] + "\n", encoding="utf-8")
    dry_run_path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + dry_run_command[0] + "\n", encoding="utf-8")
    import_path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + import_command[0] + "\n", encoding="utf-8")
    inspect_path.chmod(0o755)
    dry_run_path.chmod(0o755)
    import_path.chmod(0o755)
    readme_lines = [
        "# 春秋元泉 GEO 四平台采集包",
        "",
        "## 文件",
        "",
        f"- `observations.json`：需要填写的观测 JSON，共 {len(observations)} 条。",
        "- `work-order.md`：给采集执行者看的逐平台操作工单。",
        "- `raw-evidence/`：把截图或录屏文件放在这里，文件名与 JSON 的 `evidence_filename` 保持一致。",
        "- `inspect.sh`：检查当前包还缺哪些答案或截图，不入库。",
        "- `dry-run.sh`：只校验不入库。",
        "- `import-and-generate.sh`：正式导入，并生成成熟度报告、首篇稿件和 AI 评分。",
        "",
        "## 需要放入 raw-evidence 的文件",
        "",
        *[f"- `{filename}`" for filename in evidence_filenames],
        "",
        "## 执行顺序",
        "",
        "1. 按 `work-order.md` 打开豆包、DeepSeek、Kimi、千问网页端，复制完整答案。",
        "2. 把完整答案填入 `observations.json` 的 `raw_answer`，摘要填入 `answer_summary`。",
        "3. 截图或录屏，文件放入 `raw-evidence/`，文件名与 `evidence_filename` 一致。",
        "4. 先运行 inspect 命令查看是否还缺答案或截图。",
        "5. 再运行 dry-run 命令确认格式、四平台覆盖和证据文件存在。",
        "6. 最后运行正式导入命令，系统会生成报告、稿件和审核评分。",
        "",
        "## inspect",
        "",
        "```bash",
        inspect_command[0],
        "```",
        "",
        "## dry-run",
        "",
        "```bash",
        dry_run_command[0],
        "```",
        "",
        "## 正式导入并生成稿件",
        "",
        "```bash",
        import_command[0],
        "```",
        "",
    ]
    readme_path.write_text("\n".join(readme_lines), encoding="utf-8")
    return {
        "ok": True,
        "project_id": project_id,
        "output_dir": str(output_dir),
        "template": str(template_path),
        "work_order": str(work_order_path),
        "evidence_dir": str(evidence_dir),
        "inspect_script": str(inspect_path),
        "dry_run_script": str(dry_run_path),
        "import_script": str(import_path),
        "readme": str(readme_path),
        "observation_count": len(observations),
        "evidence_filenames": evidence_filenames,
        "template_result": template_result,
        "work_order_result": work_order_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a browser observation collection pack.")
    parser.add_argument("--project-id", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--question-limit", type=int, default=1)
    parser.add_argument("--keyword-limit", type=int, default=0)
    parser.add_argument("--platforms", default="豆包,DeepSeek,Kimi,千问")
    args = parser.parse_args()
    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()]
    result = prepare_collection_pack(
        project_id=args.project_id,
        output_dir=args.output_dir,
        question_limit=args.question_limit,
        keyword_limit=args.keyword_limit,
        platforms=platforms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
