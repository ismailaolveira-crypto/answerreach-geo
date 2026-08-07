"""Deterministic contract check for the OpenCLI DeepSeek profile collector."""

import json
import sys
import tempfile
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.v1.deepseek_worker import (  # noqa: E402
    CommandResult,
    OpenCliDeepSeekCollector,
    analyze_brand_status,
    normalize_references,
)


def main() -> None:
    calls: list[list[str]] = []
    state = {"deleted": False}
    artifact_root: Path

    def fake_runner(arguments: list[str], _timeout: int) -> CommandResult:
        calls.append(arguments)
        if "wait" in arguments:
            return CommandResult('Element "textarea" appeared', "", 0)
        if "screenshot" in arguments:
            Path(arguments[arguments.index("screenshot") + 1]).write_bytes(b"fake-png")
            return CommandResult("{}", "", 0)
        if "eval" in arguments:
            script = arguments[arguments.index("eval") + 1]
            if "document.querySelectorAll('.ds-message').length" in script:
                return CommandResult("0", "", 0)
            if "ds-toggle-button" in script:
                return CommandResult(json.dumps({"ok": True}), "", 0)
            if "document.execCommand('insertText'" in script:
                return CommandResult(json.dumps({"ok": True}), "", 0)
            if "setTimeout(()=>b.click(),0)" in script:
                return CommandResult(json.dumps({"ok": True, "method": "button"}), "", 0)
            if "const bs=Array.from(document.querySelectorAll('.ds-message'))" in script:
                return CommandResult(json.dumps({"count": 2, "last": "推荐春秋元泉作为企业 AI 安全治理平台。", "url": "https://chat.deepseek.com/a/chat/s/new"}, ensure_ascii=False), "", 0)
            if "querySelectorAll('a[href]')" in script:
                return CommandResult(json.dumps([{"number": 1, "title": "春秋元泉官网", "url": "https://icqtoken.ichunqiu.com/"}]), "", 0)
            if "trim()==='删除'" in script or "删除该对话" in script:
                raw_files = list(artifact_root.rglob("answer.json"))
                assert raw_files and raw_files[0].stat().st_size > 0, "delete ran before archive"
                state["deleted"] = True
            if "exists:Array.from" in script:
                return CommandResult(json.dumps({"url": "https://chat.deepseek.com/", "exists": False}), "", 0)
            return CommandResult(json.dumps({"value": {"ok": True}}), "", 0)
        return CommandResult("{}", "", 0)

    claim = {
        "sample_id": 7,
        "batch_id": 3,
        "run_id": 9,
        "account_id": 2,
        "account_alias": "deepseek-a02",
        "browser_profile_alias": "deepseek-real",
        "cohort": "real_user",
        "brand_name": "春秋元泉",
        "brand_aliases": ["元泉"],
        "question_plan_id": 4,
        "question": "企业 AI 安全治理平台怎么选？",
        "repeat_index": 2,
        "lease_token": "test-lease-token",
    }
    with tempfile.TemporaryDirectory() as directory:
        artifact_root = Path(directory)
        result = OpenCliDeepSeekCollector(fake_runner).collect(claim, artifact_root)
        assert result["brand_status"] == "cited"
        assert result["raw_artifact_uri"].startswith("file:")
        assert result["screenshot_uri"].startswith("file:")
        assert result["conversation_deleted_at"]
        assert state["deleted"] is True
    browser_calls = [command for command in calls if "browser" in command]
    assert browser_calls and browser_calls[0][:3] == ["opencli", "--profile", "deepseek-real"]
    assert browser_calls[0][-1] == "bind", "every sample must load its keeper tab before collection"
    assert all("geo-deepseek-real" in command for command in browser_calls)
    assert not any("open" in command[5:] for command in browser_calls), "bound sessions must not acquire a new tab lease"
    assert all(isinstance(argument, str) for command in calls for argument in command)
    assert analyze_brand_status("没有相关品牌", [], "春秋元泉", [])[0] == "absent"
    assert analyze_brand_status("建议优先选择春秋元泉。", [], "春秋元泉", [])[0] == "recommended"
    normalized = normalize_references([
        {"title": "- 1", "url": "https://example.com/report#ref-1"},
        {"title": "- 2", "url": "https://example.com/report#ref-2"},
    ])
    assert normalized == [{"number": 1, "title": "example.com", "url": "https://example.com/report", "domain": "example.com"}]
    print(json.dumps({"ok": True, "commands": len(calls), "archive_before_delete": True, "profile_routed": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
