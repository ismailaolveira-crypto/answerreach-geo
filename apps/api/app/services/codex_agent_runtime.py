"""Official local Codex SDK adapter used by the durable GEO action worker."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
from typing import Callable


class CodexRuntimeUnavailable(RuntimeError):
    pass


class CodexRunInterrupted(RuntimeError):
    pass


class CodexRunTimedOut(RuntimeError):
    pass


@dataclass(slots=True)
class CodexTurnResult:
    thread_id: str
    turn_id: str
    final_response: str
    usage: dict = field(default_factory=dict)
    runtime_events: list[dict] = field(default_factory=list)


def _payload_dict(payload: object) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {"value": str(payload)}


def diagnose_local_codex() -> dict:
    """Return non-secret local runtime/account state using the official SDK."""

    try:
        import openai_codex
        from openai_codex import Codex
    except ImportError as exc:
        return {
            "runtime_key": "local_codex",
            "sdk_installed": False,
            "ready": False,
            "login_status": "sdk_missing",
            "error": str(exc),
        }

    try:
        with Codex() as codex:
            account_response = codex.account()
            model_response = codex.models()
            account = getattr(account_response, "account", None)
            models = list(getattr(model_response, "data", []) or [])
            default_model = next(
                (getattr(item, "id", None) for item in models if getattr(item, "is_default", False)),
                getattr(models[0], "id", None) if models else None,
            )
            metadata = codex.metadata
            user_agent = getattr(metadata, "userAgent", None)
            return {
                "runtime_key": "local_codex",
                "sdk_installed": True,
                "sdk_version": openai_codex.__version__,
                "runtime_version": user_agent,
                "ready": account is not None and bool(models),
                "login_status": "chatgpt_authenticated" if account is not None else "login_required",
                "default_model": default_model,
                "available_models": [getattr(item, "id", "") for item in models if getattr(item, "id", "")],
                "error": None,
            }
    except Exception as exc:
        return {
            "runtime_key": "local_codex",
            "sdk_installed": True,
            "sdk_version": openai_codex.__version__,
            "ready": False,
            "login_status": "runtime_error",
            "error": str(exc)[:500],
        }


class LocalCodexRuntime:
    """Run one structured, sandboxed turn and expose real SDK notifications."""

    def run_structured(
        self,
        *,
        task_directory: Path,
        prompt: str,
        output_schema: dict,
        developer_instructions: str,
        model: str | None = None,
        thread_id: str | None = None,
        on_started: Callable[[str, str], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        timeout_seconds: float | None = 900.0,
    ) -> CodexTurnResult:
        from openai_codex import ApprovalMode, Codex, Sandbox

        task_directory = task_directory.resolve()
        task_directory.mkdir(parents=True, exist_ok=True)
        final_response = ""
        usage: dict = {}
        compact_events: list[dict] = []
        interrupted = False

        with Codex() as codex:
            if thread_id:
                thread = codex.thread_resume(
                    thread_id,
                    cwd=str(task_directory),
                    developer_instructions=developer_instructions,
                    model=model,
                    sandbox=Sandbox.workspace_write,
                    approval_mode=ApprovalMode.deny_all,
                    config={"web_search": "live"},
                )
            else:
                thread = codex.thread_start(
                    cwd=str(task_directory),
                    developer_instructions=developer_instructions,
                    model=model,
                    sandbox=Sandbox.workspace_write,
                    approval_mode=ApprovalMode.deny_all,
                    config={"web_search": "live"},
                )
            handle = thread.turn(
                prompt,
                output_schema=output_schema,
                sandbox=Sandbox.workspace_write,
                approval_mode=ApprovalMode.deny_all,
            )
            if on_started:
                on_started(thread.id, handle.id)

            completed_status = ""
            turn_finished = threading.Event()
            timeout_reached = threading.Event()
            timeout_thread: threading.Thread | None = None
            stream_error: Exception | None = None
            if timeout_seconds is not None and timeout_seconds > 0:
                def interrupt_after_timeout() -> None:
                    if turn_finished.wait(float(timeout_seconds)):
                        return
                    timeout_reached.set()
                    try:
                        handle.interrupt()
                    except Exception:
                        return

                timeout_thread = threading.Thread(
                    target=interrupt_after_timeout,
                    name=f"codex-turn-timeout-{handle.id}",
                    daemon=True,
                )
                timeout_thread.start()
            try:
                for notification in handle.stream():
                    detail = _payload_dict(notification.payload)
                    if notification.method in {
                        "turn/started",
                        "item/started",
                        "item/completed",
                        "thread/tokenUsage/updated",
                        "turn/completed",
                    }:
                        compact_events.append({"method": notification.method, "detail": detail})
                    if on_event:
                        on_event(notification.method, detail)
                    if notification.method == "item/completed":
                        item = detail.get("item") or {}
                        if item.get("type") == "agentMessage" and item.get("phase") == "final_answer":
                            final_response = str(item.get("text") or "")
                    elif notification.method == "thread/tokenUsage/updated":
                        usage = detail.get("tokenUsage") or {}
                    elif notification.method == "turn/completed":
                        completed_status = str((detail.get("turn") or {}).get("status") or "")

                    if (
                        cancellation_requested
                        and cancellation_requested()
                        and not interrupted
                        and notification.method != "turn/completed"
                    ):
                        handle.interrupt()
                        interrupted = True
            except Exception as exc:
                stream_error = exc
            finally:
                turn_finished.set()
                if timeout_thread is not None:
                    timeout_thread.join(timeout=1)

        if timeout_reached.is_set():
            raise CodexRunTimedOut(
                f"Codex turn exceeded {float(timeout_seconds or 0):g} seconds"
            ) from stream_error
        if stream_error is not None:
            raise stream_error
        if interrupted or completed_status in {"interrupted", "cancelled", "canceled"}:
            raise CodexRunInterrupted("Codex turn was interrupted by the user")
        if completed_status != "completed":
            raise CodexRuntimeUnavailable(f"Codex turn ended with status: {completed_status or 'unknown'}")
        if not final_response.strip():
            raise CodexRuntimeUnavailable("Codex returned no final structured response")
        try:
            json.loads(final_response)
        except json.JSONDecodeError as exc:
            raise CodexRuntimeUnavailable("Codex final response is not valid JSON") from exc
        return CodexTurnResult(
            thread_id=thread.id,
            turn_id=handle.id,
            final_response=final_response,
            usage=usage,
            runtime_events=compact_events,
        )
