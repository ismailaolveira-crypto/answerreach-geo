"""Out-of-process DeepSeek web collector routed by independent OpenCLI profiles."""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.v1.evidence_analysis import analyze_brand_status


class CollectionError(RuntimeError):
    def __init__(self, code: str, detail: str, outcome: str = "retryable") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.outcome = outcome


def _decode_json(raw: str) -> Any:
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise CollectionError("opencli_invalid_json", "OpenCLI 未返回可解析的结构化结果")


def _rows(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("data", "rows", "result", "value"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [value]
    return []


def _history_urls(value: Any) -> list[str]:
    urls: list[str] = []
    for row in _rows(value):
        url = row.get("Url") or row.get("url")
        if isinstance(url, str) and "/a/chat/s/" in url:
            urls.append(url)
    return urls


def _answer_text(value: Any) -> str:
    for row in _rows(value):
        answer = row.get("response") or row.get("Response") or row.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
    raise CollectionError("empty_answer", "DeepSeek 已结束响应，但未提取到回答正文")


def normalize_references(rows: list[dict]) -> list[dict]:
    """Collapse repeated footnote anchors into auditable source URLs."""
    references: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        raw_url = row.get("url")
        if not isinstance(raw_url, str) or not raw_url.startswith(("http://", "https://")):
            continue
        parts = urlsplit(raw_url)
        canonical_url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))
        if canonical_url in seen:
            continue
        seen.add(canonical_url)
        domain = parts.hostname or parts.netloc or "未识别来源"
        raw_title = str(row.get("title") or "").strip()
        title = domain if not raw_title or re.fullmatch(r"[\s\-–—·#\d.]+", raw_title) else raw_title
        references.append({"number": len(references) + 1, "title": title, "url": canonical_url, "domain": domain})
    return references


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


Runner = Callable[[list[str], int], CommandResult]


def run_command(arguments: list[str], timeout_seconds: int) -> CommandResult:
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
        return CommandResult(completed.stdout, completed.stderr, completed.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(stdout, f"{stderr}\ncommand timed out after {timeout_seconds}s", 124)


class OpenCliDeepSeekCollector:
    def __init__(self, runner: Runner = run_command) -> None:
        self.runner = runner

    def _call(self, profile: str, arguments: list[str], timeout: int = 150) -> Any:
        command = ["opencli", "--profile", profile, *arguments, "-f", "json"]
        result = self.runner(command, timeout)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-1200:]
            lowered = detail.lower()
            if any(token in lowered for token in ("login", "sign in", "unauthorized", "authentication")):
                raise CollectionError("auth_expired", detail or "DeepSeek 登录已失效", "auth_expired")
            if any(token in lowered for token in ("rate", "too many", "429", "频繁")):
                raise CollectionError("rate_limited", detail or "DeepSeek 请求过于频繁", "rate_limited")
            raise CollectionError("opencli_failed", detail or "OpenCLI 浏览器命令执行失败")
        return _decode_json(result.stdout)

    def _browser(self, profile: str, session: str, arguments: list[str], timeout: int = 60) -> Any:
        command = ["opencli", "--profile", profile, "browser", session, *arguments]
        result = self.runner(command, timeout)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-1200:]
            raise CollectionError("opencli_browser_failed", detail or "OpenCLI 浏览器控制命令失败")
        # OpenCLI's wait command reports success as a human-readable sentence
        # (for example: `Element "..." appeared`) rather than JSON.
        if arguments and arguments[0] == "wait":
            return {"ok": True, "detail": result.stdout.strip()}
        # Some successful browser bridge commands (notably `wait`) intentionally
        # produce no stdout.  Treat that as a successful command without a
        # payload instead of turning it into a misleading JSON parse failure.
        if not result.stdout.strip():
            return None
        return _decode_json(result.stdout)

    def _wait_for_new_conversation(self, profile: str, before: set[str]) -> str:
        for _ in range(10):
            history = self._call(
                profile,
                ["deepseek", "history", "--limit", "20", "--window", "background", "--keep-tab", "false"],
                40,
            )
            urls = _history_urls(history)
            created = [url for url in urls if url not in before]
            if created:
                return created[0]
            time.sleep(1)
        raise CollectionError("conversation_url_missing", "回答已返回，但未找到本次新建的 DeepSeek 会话")

    def _extract_references(self, profile: str, session: str) -> list[dict]:
        script = """(() => Array.from(document.querySelectorAll('a[href]')).map((a,i)=>({number:i+1,title:(a.innerText||a.textContent||'').trim(),url:a.href})).filter(x=>x.title&&/^https?:/.test(x.url)&&!x.url.includes('chat.deepseek.com')).slice(0,30))()"""
        value = self._browser(profile, session, ["eval", script], 30)
        rows = _rows(value)
        if len(rows) == 1 and isinstance(rows[0].get("value"), list):
            rows = [item for item in rows[0]["value"] if isinstance(item, dict)]
        return normalize_references(rows)

    def _delete_conversation(self, profile: str, session: str, conversation_url: str) -> None:
        conversation_id = conversation_url.rstrip("/").split("/")[-1]
        open_menu = f"""(() => {{const a=Array.from(document.querySelectorAll('a[href*="/a/chat/s/"]')).find(x=>x.href.includes('{conversation_id}'));if(!a)return {{ok:false,stage:'link'}};let n=a;for(let i=0;i<6&&n;i++,n=n.parentElement){{n.dispatchEvent(new MouseEvent('mouseenter',{{bubbles:true}}));const bs=Array.from(n.querySelectorAll('button,[role=button]')).filter(x=>x!==a);if(bs.length){{bs[bs.length-1].click();return {{ok:true,stage:'menu'}};}}}}return {{ok:false,stage:'menu'}};}})()"""
        click_delete = """(() => {const visible=x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0};const xs=Array.from(document.querySelectorAll('button,[role=button],div,span')).filter(x=>{const t=(x.innerText||x.textContent||'').trim();return visible(x)&&(t==='删除'||t==='删除该对话')});if(!xs.length)return {ok:false};xs[xs.length-1].click();return {ok:true,count:xs.length};})()"""
        self._browser(profile, session, ["eval", open_menu], 30)
        self._browser(profile, session, ["wait", "time", "1"], 10)
        self._browser(profile, session, ["eval", click_delete], 30)
        self._browser(profile, session, ["wait", "time", "1"], 10)
        self._browser(profile, session, ["eval", click_delete], 30)
        ui_removed = False
        for _ in range(8):
            state = self._browser(
                profile,
                session,
                ["eval", f"({{url:location.href,exists:Array.from(document.querySelectorAll('a[href*=\\\"/a/chat/s/\\\"]')).some(a=>a.href.includes('{conversation_id}'))}})"],
                30,
            )
            if isinstance(state, dict) and conversation_id not in str(state.get("url", "")) and state.get("exists") is False:
                ui_removed = True
                break
            time.sleep(1)
        if not ui_removed:
            raise CollectionError("conversation_delete_failed", "证据已保存，但 DeepSeek 会话删除验证失败")

        # A client-side route change can briefly hide a conversation before the
        # server deletion has propagated. Reload the provider page and verify the
        # same conversation id is still absent from freshly loaded history.
        self._browser(
            profile,
            session,
            ["eval", "(() => { setTimeout(() => location.reload(), 0); return {ok:true}; })()"],
            30,
        )
        self._browser(
            profile,
            session,
            ["wait", "selector", 'textarea[placeholder*="DeepSeek"]', "--timeout", "15000"],
            25,
        )
        server_state = self._browser(
            profile,
            session,
            ["eval", f"({{url:location.href,exists:Array.from(document.querySelectorAll('a[href*=\\\"/a/chat/s/\\\"]')).some(a=>a.href.includes('{conversation_id}'))}})"],
            30,
        )
        if isinstance(server_state, dict) and server_state.get("exists") is False:
            return
        raise CollectionError("conversation_delete_failed", "页面刷新后会话仍然存在，未通过服务端删除验证")

    def _bound_answer(self, profile: str, session: str, prompt: str) -> tuple[str, str]:
        # Load the keeper tab for this account at the beginning of every sample.
        # This lets the product worker recover the current tab target after a
        # provider-side reload instead of requiring an operator to bind it for
        # every question.
        self._browser(profile, session, ["bind"], 30)
        # `browser open` obtains a new tab lease.  Using it on a session already
        # bound to a user's profile tab can switch target ids and detach the
        # Chrome debugger.  Navigate inside the bound tab instead so the profile
        # identity and debugger attachment stay stable for the whole sample.
        self._browser(
            profile,
            session,
            [
                "eval",
                "(() => { if (location.href !== 'https://chat.deepseek.com/') location.assign('https://chat.deepseek.com/'); return {ok:true}; })()",
            ],
            20,
        )
        self._browser(
            profile,
            session,
            ["wait", "selector", 'textarea[placeholder*="DeepSeek"]', "--timeout", "15000"],
            25,
        )
        baseline = self._browser(
            profile, session, ["eval", "document.querySelectorAll('.ds-message').length"], 20
        )
        baseline_count = int(baseline) if isinstance(baseline, (int, float)) else 0
        self._browser(
            profile,
            session,
            ["eval", "(() => {const b=Array.from(document.querySelectorAll('.ds-toggle-button'))[1];if(!b)return {ok:false};if(!b.classList.contains('ds-toggle-button--selected'))b.click();return {ok:true};})()"],
            20,
        )
        prompt_json = json.dumps(prompt, ensure_ascii=False)
        filled = self._browser(
            profile,
            session,
            ["eval", f"""(()=>{{const box=document.querySelector('textarea[placeholder*="DeepSeek"]');if(!box)return {{ok:false}};box.focus();box.value='';document.execCommand('selectAll');document.execCommand('insertText',false,{prompt_json});box.dispatchEvent(new Event('input',{{bubbles:true}}));return {{ok:true}};}})()"""],
            30,
        )
        if not isinstance(filled, dict) or filled.get("ok") is not True:
            raise CollectionError("fill_failed", "未能把问题填入 DeepSeek")
        self._browser(profile, session, ["wait", "time", "1"], 10)
        sent = self._browser(
            profile,
            session,
            ["eval", """(()=>{const box=document.querySelector('textarea[placeholder*="DeepSeek"]');if(!box)return {ok:false};let c=box.parentElement;while(c&&!c.querySelector('div[role="button"]'))c=c.parentElement;if(c){const bs=c.querySelectorAll('div[role="button"]:not(.ds-toggle-button)');const b=bs[bs.length-1];if(b&&b.getAttribute('aria-disabled')==='false'){setTimeout(()=>b.click(),0);return {ok:true,method:'button'};}}setTimeout(()=>box.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,bubbles:true})),0);return {ok:true,method:'enter'};})()"""],
            30,
        )
        if not isinstance(sent, dict) or sent.get("ok") is not True:
            raise CollectionError("send_failed", "未能把问题发送到 DeepSeek")
        last_text = ""
        stable = 0
        for _ in range(55):
            time.sleep(3)
            state = self._browser(
                profile,
                session,
                ["eval", "(() => {const bs=Array.from(document.querySelectorAll('.ds-message'));const ts=bs.map(b=>(b.innerText||'').trim()).filter(Boolean);return {count:ts.length,last:ts[ts.length-1]||'',url:location.href};})()"],
                30,
            )
            if not isinstance(state, dict):
                continue
            candidate = str(state.get("last") or "").strip()
            if int(state.get("count") or 0) > baseline_count and candidate and candidate != prompt.strip():
                stable = stable + 1 if candidate == last_text else 0
                last_text = candidate
                if stable >= 2:
                    url = str(state.get("url") or "")
                    if "/a/chat/s/" not in url:
                        raise CollectionError("conversation_url_missing", "回答已返回，但没有获得会话地址")
                    return candidate, url
        raise CollectionError("answer_timeout", "DeepSeek 回答在 165 秒内没有稳定完成", "retryable")

    def collect(self, claim: dict, artifact_root: Path) -> dict:
        profile = claim["browser_profile_alias"]
        sample_id = int(claim["sample_id"])
        session = f"geo-{profile}"
        sample_dir = artifact_root / f"batch-{claim['batch_id']}" / f"sample-{sample_id}"
        sample_dir.mkdir(parents=True, exist_ok=True)
        raw_path = sample_dir / "answer.json"
        screenshot_path = sample_dir / "answer.png"
        answer, conversation_url = self._bound_answer(profile, session, claim["question"])
        captured_at = datetime.now(timezone.utc)
        references = self._extract_references(profile, session)
        screenshot_result = self.runner(
            [
                "opencli", "--profile", profile, "browser", session, "screenshot",
                str(screenshot_path), "--full-page",
            ],
            60,
        )
        if screenshot_result.returncode != 0 or not screenshot_path.exists():
            raise CollectionError("screenshot_failed", "回答已获得，但截图工件保存失败")
        raw_payload = {
                "schema_version": "spring-yuan-deepseek-profile-sample/v1",
                "sample_id": sample_id,
                "batch_id": claim["batch_id"],
                "account_alias": claim["account_alias"],
                "cohort": claim["cohort"],
                "question": claim["question"],
                "repeat_index": claim["repeat_index"],
                "answer": answer,
                "references": references,
                "conversation_url": conversation_url,
                "captured_at": captured_at.isoformat(),
        }
        raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not raw_path.exists() or raw_path.stat().st_size == 0:
            raise CollectionError("archive_failed", "原始回答工件保存失败")
        self._delete_conversation(profile, session, conversation_url)
        deleted_at = datetime.now(timezone.utc)
        brand_status, brand_position = analyze_brand_status(
            answer,
            references,
            claim["brand_name"],
            claim.get("brand_aliases", []),
        )
        return {
            "answer_text": answer,
            "references": references,
            "brand_status": brand_status,
            "brand_position": brand_position,
            "competitor_positions": [],
            "conversation_url": conversation_url,
            "raw_artifact_uri": raw_path.resolve().as_uri(),
            "screenshot_uri": screenshot_path.resolve().as_uri(),
            "captured_at": captured_at.isoformat(),
            "conversation_deleted_at": deleted_at.isoformat(),
            "sampling_environment": {
                "transport": "opencli_bound_profile_tab",
                "search_enabled": True,
                "model_mode": "instant",
                "new_conversation": True,
            },
        }


class WorkerApiClient:
    def __init__(self, api_base_url: str, token: str, workspace_id: int) -> None:
        self.base = api_base_url.rstrip("/") + f"/api/v1/workspaces/{workspace_id}"
        self.token = token

    def request(self, method: str, path: str, payload: dict) -> dict:
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode())
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise CollectionError(f"api_{exc.code}", detail, "fatal") from exc

    def claim(self, worker_id: str) -> dict:
        return self.request("POST", "/sampling-worker/claim", {"worker_id": worker_id})

    def complete(self, sample_id: int, lease_token: str, result: dict) -> dict:
        return self.request("POST", f"/sampling-worker/samples/{sample_id}/complete", {"lease_token": lease_token, **result})

    def fail(self, sample_id: int, lease_token: str, error: CollectionError) -> dict:
        return self.request("POST", f"/sampling-worker/samples/{sample_id}/fail", {
            "lease_token": lease_token,
            "error_code": error.code,
            "error_detail": error.detail,
            "outcome": error.outcome,
        })
