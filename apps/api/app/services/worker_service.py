"""Bounded control of the repository-owned macOS queue Worker service.

The public API never accepts a command, path, label, or environment value.  It
can only inspect or repair the one LaunchAgent shipped by this repository.
Queue recovery remains a separate database operation so OS supervision and
business state do not become one opaque side effect.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess


WORKER_SERVICE_LABEL = "com.chunqiu-yuanquan.geo.worker"
FULL_STACK_SERVICE_LABEL = "com.chunqiu-yuanquan.geo.stack"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
EXPECTED_API_DIR = PROJECT_ROOT / "apps" / "api"
WORKER_INSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "install-macos-worker-service.sh"
WORKER_REPAIR_SCRIPT = PROJECT_ROOT / "scripts" / "repair-macos-worker-service.sh"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str], float], CommandResult]


@dataclass(frozen=True)
class ManagedWorkerServiceStatus:
    supported: bool
    installed: bool
    running: bool
    repository_match: bool
    state: str
    pid: int | None
    label: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ManagedWorkerRepairResult:
    attempted: bool
    action: str
    status: ManagedWorkerServiceStatus
    message: str

    def as_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "action": self.action,
            "status": self.status.as_dict(),
            "message": self.message,
        }


def _run_command(args: Sequence[str], timeout_seconds: float) -> CommandResult:
    completed = subprocess.run(
        list(args),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _service_target(label: str) -> str:
    return f"gui/{os.getuid()}/{label}"


def _service_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{WORKER_SERVICE_LABEL}.plist"


def _plist_repository_matches(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return False
    working_directory = Path(str(payload.get("WorkingDirectory") or "")).resolve()
    return working_directory == EXPECTED_API_DIR.resolve()


def _parse_launchd_state(output: str) -> tuple[str, int | None]:
    state_match = re.search(r"^\s*state\s*=\s*(\S+)\s*$", output, re.MULTILINE)
    pid_match = re.search(r"^\s*pid\s*=\s*(\d+)\s*$", output, re.MULTILINE)
    return (
        state_match.group(1) if state_match else "loaded",
        int(pid_match.group(1)) if pid_match else None,
    )


def inspect_managed_worker_service(
    *, runner: CommandRunner = _run_command, system_name: str | None = None
) -> ManagedWorkerServiceStatus:
    if (system_name or platform.system()) != "Darwin":
        return ManagedWorkerServiceStatus(
            supported=False,
            installed=False,
            running=False,
            repository_match=False,
            state="unsupported",
            pid=None,
            label=WORKER_SERVICE_LABEL,
            message="当前运行方式不使用 macOS 常驻服务。",
        )

    plist_path = _service_plist_path()
    repository_match = plist_path.exists() and _plist_repository_matches(plist_path)
    result = runner(["/bin/launchctl", "print", _service_target(WORKER_SERVICE_LABEL)], 3)
    installed = result.returncode == 0 or plist_path.exists()
    if not installed:
        return ManagedWorkerServiceStatus(
            supported=True,
            installed=False,
            running=False,
            repository_match=True,
            state="not_installed",
            pid=None,
            label=WORKER_SERVICE_LABEL,
            message="当前仓库尚未安装 Worker 常驻服务。",
        )
    if not repository_match:
        return ManagedWorkerServiceStatus(
            supported=True,
            installed=True,
            running=False,
            repository_match=False,
            state="repository_conflict",
            pid=None,
            label=WORKER_SERVICE_LABEL,
            message="Worker 常驻服务属于另一份项目副本，已拒绝接管。",
        )
    if result.returncode != 0:
        return ManagedWorkerServiceStatus(
            supported=True,
            installed=True,
            running=False,
            repository_match=True,
            state="stopped",
            pid=None,
            label=WORKER_SERVICE_LABEL,
            message="Worker 常驻服务已安装，正在等待系统拉起。",
        )
    state, pid = _parse_launchd_state(result.stdout)
    running = state == "running" and pid is not None
    return ManagedWorkerServiceStatus(
        supported=True,
        installed=True,
        running=running,
        repository_match=True,
        state=state,
        pid=pid,
        label=WORKER_SERVICE_LABEL,
        message="Worker 已由系统守护。" if running else "Worker 常驻服务正在恢复。",
    )


def repair_managed_worker_service(
    *, runner: CommandRunner = _run_command, system_name: str | None = None
) -> ManagedWorkerRepairResult:
    before = inspect_managed_worker_service(runner=runner, system_name=system_name)
    if not before.supported:
        return ManagedWorkerRepairResult(
            attempted=False,
            action="unsupported",
            status=before,
            message=before.message,
        )
    if not before.repository_match:
        return ManagedWorkerRepairResult(
            attempted=False,
            action="repository_conflict",
            status=before,
            message=before.message,
        )

    script = WORKER_REPAIR_SCRIPT if before.installed else WORKER_INSTALL_SCRIPT
    action = "restarted" if before.installed else "installed"
    result = runner(["/bin/bash", str(script)], 45)
    after = inspect_managed_worker_service(runner=runner, system_name=system_name)
    if result.returncode != 0:
        return ManagedWorkerRepairResult(
            attempted=True,
            action="failed",
            status=after,
            message="Worker 修复未完成，请查看本机服务状态。",
        )
    return ManagedWorkerRepairResult(
        attempted=True,
        action=action,
        status=after,
        message="Worker 常驻服务已安装并启动。" if action == "installed" else "Worker 常驻服务已重新拉起。",
    )
