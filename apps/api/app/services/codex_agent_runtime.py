"""Official local Codex SDK adapter used by the durable GEO action worker."""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import threading
from time import monotonic
from typing import Callable


class CodexRuntimeUnavailable(RuntimeError):
    pass


class CodexRuntimeCapacityBusy(CodexRuntimeUnavailable):
    pass


class CodexRunInterrupted(RuntimeError):
    pass


class CodexRunTimedOut(RuntimeError):
    pass


_DIAGNOSTIC_CACHE_TTL_SECONDS = 60.0
_diagnostic_cache: tuple[float, dict] | None = None
_diagnostic_cache_lock = threading.Lock()


@dataclass(slots=True)
class _WarmCodexSlot:
    client: object
    connected_since: datetime
    reuse_count: int = 0
    in_use: bool = False


class _WarmCodexClientPool:
    """Lazily keep up to ten independent SDK clients warm per process."""

    def __init__(self, max_size: int = 10) -> None:
        self._max_size = max(1, min(int(max_size), 10))
        self._condition = threading.Condition(threading.RLock())
        self._slots: list[_WarmCodexSlot] = []

    @contextmanager
    def use(self, *, timeout_seconds: float = 30.0):
        slot: _WarmCodexSlot
        deadline = monotonic() + max(0.1, float(timeout_seconds))
        with self._condition:
            while True:
                slot = next((candidate for candidate in self._slots if not candidate.in_use), None)
                if slot is not None:
                    break
                if len(self._slots) < self._max_size:
                    from openai_codex import Codex

                    slot = _WarmCodexSlot(
                        client=Codex(),
                        connected_since=datetime.now(timezone.utc),
                    )
                    self._slots.append(slot)
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise CodexRuntimeCapacityBusy(
                        f"Codex client capacity remained busy for {timeout_seconds:g} seconds"
                    )
                self._condition.wait(remaining)
            slot.in_use = True
            slot.reuse_count += 1

        invalid = False
        try:
            yield slot.client
        except BaseException:
            invalid = True
            raise
        finally:
            client_to_close: object | None = None
            with self._condition:
                if invalid:
                    if slot in self._slots:
                        self._slots.remove(slot)
                    client_to_close = slot.client
                else:
                    slot.in_use = False
                self._condition.notify()
            self._close_client(client_to_close)

    def snapshot(self) -> dict:
        with self._condition:
            connected_since = min(
                (slot.connected_since for slot in self._slots),
                default=None,
            )
            return {
                "connection_status": "warm" if self._slots else "cold",
                "connected_since": connected_since.isoformat() if connected_since else None,
                "reuse_count": sum(slot.reuse_count for slot in self._slots),
                "pool_size": len(self._slots),
                "pool_busy": sum(1 for slot in self._slots if slot.in_use),
                "pool_limit": self._max_size,
            }

    def reset(self) -> None:
        with self._condition:
            clients = [slot.client for slot in self._slots]
            self._slots.clear()
            self._condition.notify_all()
        for client in clients:
            self._close_client(client)

    @staticmethod
    def _close_client(client: object | None) -> None:
        if client is None:
            return
        try:
            client.close()
        except Exception:
            pass


_warm_codex_client = _WarmCodexClientPool(max_size=10)
atexit.register(_warm_codex_client.reset)


def reset_local_codex_client() -> None:
    """Discard all warm SDK processes during shutdown or deterministic tests."""

    _warm_codex_client.reset()


@dataclass(slots=True)
class CodexTurnResult:
    thread_id: str
    turn_id: str
    final_response: str
    usage: dict = field(default_factory=dict)
    runtime_events: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class CodexImageResult:
    """One real image produced by the local Codex imagegen skill."""

    thread_id: str
    turn_id: str
    saved_path: Path
    revised_prompt: str | None = None
    usage: dict = field(default_factory=dict)


def _payload_dict(payload: object) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {"value": str(payload)}


def _probe_local_codex() -> dict:
    """Read non-secret local runtime/account state using the official SDK."""

    try:
        import openai_codex
    except ImportError as exc:
        return {
            "runtime_key": "local_codex",
            "sdk_installed": False,
            "ready": False,
            "login_status": "sdk_missing",
            "error": str(exc),
        }

    try:
        with _warm_codex_client.use(timeout_seconds=0.1) as codex:
            account_response = codex.account()
            model_response = codex.models()
            account = getattr(account_response, "account", None)
            models = list(getattr(model_response, "data", []) or [])
            default_model = next(
                (getattr(item, "id", None) for item in models if getattr(item, "is_default", False)),
                getattr(models[0], "id", None) if models else None,
            )
            model_options = []
            for item in models:
                model_id = str(getattr(item, "id", "") or "")
                if not model_id:
                    continue
                supported_efforts = [
                    str(getattr(getattr(option, "reasoning_effort", None), "value", "") or "")
                    for option in list(getattr(item, "supported_reasoning_efforts", []) or [])
                ]
                supported_efforts = [value for value in supported_efforts if value]
                default_effort = str(
                    getattr(getattr(item, "default_reasoning_effort", None), "value", "") or ""
                )
                model_options.append(
                    {
                        "id": model_id,
                        "display_name": str(getattr(item, "display_name", "") or model_id),
                        "description": str(getattr(item, "description", "") or ""),
                        "default_reasoning_effort": default_effort or None,
                        "supported_reasoning_efforts": supported_efforts,
                    }
                )
            default_model_option = next(
                (item for item in model_options if item["id"] == default_model),
                model_options[0] if model_options else None,
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
                "default_reasoning_effort": (
                    default_model_option.get("default_reasoning_effort")
                    if default_model_option
                    else None
                ),
                "available_models": [item["id"] for item in model_options],
                "model_options": model_options,
                "error": None,
                **_warm_codex_client.snapshot(),
            }
    except CodexRuntimeCapacityBusy as exc:
        return {
            "runtime_key": "local_codex",
            "sdk_installed": True,
            "sdk_version": openai_codex.__version__,
            "ready": False,
            "login_status": "capacity_busy",
            "error": str(exc),
            **_warm_codex_client.snapshot(),
        }
    except Exception as exc:
        return {
            "runtime_key": "local_codex",
            "sdk_installed": True,
            "sdk_version": openai_codex.__version__,
            "ready": False,
            "login_status": "runtime_error",
            "error": str(exc)[:500],
            **_warm_codex_client.snapshot(),
        }


def invalidate_local_codex_diagnostic_cache() -> None:
    """Force the next diagnostic to read the live local Codex runtime."""

    global _diagnostic_cache
    with _diagnostic_cache_lock:
        _diagnostic_cache = None


def diagnose_local_codex() -> dict:
    """Return a short-lived, non-secret Codex diagnostic snapshot.

    Account and model discovery starts a local Codex process and can take several
    seconds. Page reads may reuse the snapshot, while explicit tests and run
    creation invalidate it first.
    """

    global _diagnostic_cache
    now = monotonic()
    cached = _diagnostic_cache
    if cached and now - cached[0] < _DIAGNOSTIC_CACHE_TTL_SECONDS:
        return dict(cached[1])
    with _diagnostic_cache_lock:
        now = monotonic()
        cached = _diagnostic_cache
        if cached and now - cached[0] < _DIAGNOSTIC_CACHE_TTL_SECONDS:
            return dict(cached[1])
        result = _probe_local_codex()
        if result.get("login_status") == "capacity_busy":
            return dict(result)
        _diagnostic_cache = (monotonic(), dict(result))
        return dict(result)


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
        reasoning_effort: str | None = None,
        thread_id: str | None = None,
        on_started: Callable[[str, str], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        timeout_seconds: float | None = 900.0,
    ) -> CodexTurnResult:
        from openai_codex import ApprovalMode, Sandbox
        from openai_codex.types import ReasoningEffort

        task_directory = task_directory.resolve()
        task_directory.mkdir(parents=True, exist_ok=True)
        final_response = ""
        usage: dict = {}
        compact_events: list[dict] = []
        interrupted = False

        with _warm_codex_client.use(
            timeout_seconds=min(float(timeout_seconds), 30.0)
            if timeout_seconds and timeout_seconds > 0
            else 30.0
        ) as codex:
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
                effort=ReasoningEffort(reasoning_effort) if reasoning_effort else None,
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
            if interrupted or completed_status in {
                "interrupted",
                "cancelled",
                "canceled",
            }:
                raise CodexRunInterrupted("Codex turn was interrupted by the user")
            if completed_status != "completed":
                raise CodexRuntimeUnavailable(
                    f"Codex turn ended with status: {completed_status or 'unknown'}"
                )
            if not final_response.strip():
                raise CodexRuntimeUnavailable("Codex returned no final structured response")
            try:
                json.loads(final_response)
            except json.JSONDecodeError as exc:
                raise CodexRuntimeUnavailable(
                    "Codex final response is not valid JSON"
                ) from exc
            return CodexTurnResult(
                thread_id=thread.id,
                turn_id=handle.id,
                final_response=final_response,
                usage=usage,
                runtime_events=compact_events,
            )

    def run_image_generation(
        self,
        *,
        task_directory: Path,
        prompt: str,
        model: str | None = None,
        timeout_seconds: float = 900.0,
        on_started: Callable[[str, str], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> CodexImageResult:
        """Generate one image through Codex's installed ``imagegen`` skill.

        The image is copied into the caller-owned task directory before this
        method returns.  A successful text response without a real readable
        image artifact is treated as a failure.
        """

        from openai_codex import ApprovalMode, Sandbox, SkillInput, TextInput

        task_directory = task_directory.resolve()
        task_directory.mkdir(parents=True, exist_ok=True)
        skill_path = Path.home() / ".codex" / "skills" / ".system" / "imagegen" / "SKILL.md"
        if not skill_path.is_file():
            raise CodexRuntimeUnavailable("Codex imagegen skill is not installed")

        generated_path: Path | None = None
        revised_prompt: str | None = None
        usage: dict = {}
        completed_status = ""
        with _warm_codex_client.use(timeout_seconds=min(float(timeout_seconds), 30.0)) as codex:
            thread = codex.thread_start(
                cwd=str(task_directory),
                developer_instructions=(
                    "Generate exactly one image for an article. Do not publish or contact anyone. "
                    "Use the imagegen skill and return only after the image artifact is saved."
                ),
                model=model,
                sandbox=Sandbox.workspace_write,
                approval_mode=ApprovalMode.deny_all,
                config={"web_search": "disabled"},
                ephemeral=True,
            )
            handle = thread.turn(
                [
                    SkillInput(name="imagegen", path=str(skill_path)),
                    TextInput(text=prompt),
                ],
                sandbox=Sandbox.workspace_write,
                approval_mode=ApprovalMode.deny_all,
            )
            if on_started:
                on_started(thread.id, handle.id)

            turn_finished = threading.Event()
            timeout_reached = threading.Event()

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
                name=f"codex-image-timeout-{handle.id}",
                daemon=True,
            )
            timeout_thread.start()
            try:
                for notification in handle.stream():
                    detail = _payload_dict(notification.payload)
                    if on_event:
                        on_event(notification.method, detail)
                    if notification.method == "item/completed":
                        item = detail.get("item") or {}
                        if str(item.get("type") or "") in {
                            "imageGeneration",
                            "image_generation_call",
                        }:
                            path_value = item.get("savedPath") or item.get("saved_path")
                            if path_value:
                                generated_path = Path(str(path_value)).expanduser().resolve()
                            revised_prompt = str(
                                item.get("revisedPrompt") or item.get("revised_prompt") or ""
                            ).strip() or None
                    elif notification.method == "thread/tokenUsage/updated":
                        usage = detail.get("tokenUsage") or {}
                    elif notification.method == "turn/completed":
                        completed_status = str((detail.get("turn") or {}).get("status") or "")
            finally:
                turn_finished.set()
                timeout_thread.join(timeout=1)

            if timeout_reached.is_set():
                raise CodexRunTimedOut(
                    f"Codex image generation exceeded {float(timeout_seconds):g} seconds"
                )
            if completed_status != "completed":
                raise CodexRuntimeUnavailable(
                    f"Codex image generation ended with status: {completed_status or 'unknown'}"
                )
            if generated_path is None or not generated_path.is_file():
                raise CodexRuntimeUnavailable("Codex returned no readable generated image artifact")

            suffix = generated_path.suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise CodexRuntimeUnavailable("Codex generated an unsupported image format")
            destination = task_directory / f"generated-image{suffix}"
            if generated_path != destination:
                shutil.copy2(generated_path, destination)
            if destination.stat().st_size <= 0:
                raise CodexRuntimeUnavailable("Codex generated an empty image artifact")
            return CodexImageResult(
                thread_id=thread.id,
                turn_id=handle.id,
                saved_path=destination,
                revised_prompt=revised_prompt,
                usage=usage,
            )
