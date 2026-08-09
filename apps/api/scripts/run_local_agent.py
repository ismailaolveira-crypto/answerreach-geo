"""Register and monitor a member computer without exporting browser credentials.

V1 deliberately reports health only. It does not accept remote shell commands or
claim GEO jobs, so an online node cannot be mistaken for completed execution.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


AGENT_VERSION = "0.1.0"
DEFAULT_CONFIG = Path.home() / ".config" / "chunqiu-yuanquan-geo" / "local-agent.json"


def _process_running(markers: tuple[str, ...]) -> bool:
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        else:
            result = subprocess.run(
                ["ps", "-axo", "comm="],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        output = result.stdout.lower()
        return any(marker.lower() in output for marker in markers)
    except (OSError, subprocess.SubprocessError):
        return False


def _codex_status() -> dict:
    executable = shutil.which("codex")
    if not executable:
        return {"installed": False, "logged_in": False}
    logged_in = False
    try:
        result = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        summary = f"{result.stdout}\n{result.stderr}".lower()
        logged_in = result.returncode == 0 and not any(
            marker in summary for marker in ("not logged", "unauthenticated", "login required")
        )
    except (OSError, subprocess.SubprocessError):
        logged_in = False
    return {"installed": True, "logged_in": logged_in}


def collect_status() -> tuple[dict, dict]:
    egolite_paths = (
        Path("/Applications/ego lite.app"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ego lite" / "ego lite.exe",
    )
    egolite_installed = any(path.exists() for path in egolite_paths if str(path))
    egolite_running = _process_running(("ego lite", "egolite"))
    codex = _codex_status()
    capabilities = {
        "execution_mode": "status_only",
        "remote_job_execution": False,
        "egolite": {"installed": egolite_installed},
        "codex": {"installed": codex["installed"]},
    }
    health = {
        "egolite": {"running": egolite_running, "login_state_inspected": False},
        "codex": {"logged_in": codex["logged_in"]},
    }
    return capabilities, health


def _request(method: str, url: str, payload: dict, agent_token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if agent_token:
        headers["X-Geo-Agent-Token"] = agent_token
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        method=method,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Local Agent API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach GEO host: {exc.reason}") from exc


def _write_config(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read_config(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Local Agent is not enrolled. Missing config: {path}") from exc


def enroll(args: argparse.Namespace) -> None:
    capabilities, health = collect_status()
    server = args.server.rstrip("/")
    response = _request(
        "POST",
        f"{server}/api/v1/local-agent/enroll",
        {
            "enrollment_token": args.token,
            "name": args.name or socket.gethostname(),
            "hostname": socket.gethostname(),
            "platform": f"{platform.system()} {platform.release()}",
            "agent_version": AGENT_VERSION,
            "capabilities": capabilities,
            "health": health,
        },
    )
    config = {
        "server": server,
        "workspace_id": response["workspace_id"],
        "node_id": response["id"],
        "device_token": response["device_token"],
    }
    _write_config(args.config, config)
    print(
        json.dumps(
            {
                "enrolled": True,
                "workspace_id": config["workspace_id"],
                "node_id": config["node_id"],
                "config": str(args.config),
                "execution_mode": "status_only",
            },
            ensure_ascii=False,
        )
    )


def heartbeat(config: dict) -> dict:
    capabilities, health = collect_status()
    return _request(
        "POST",
        f"{config['server'].rstrip('/')}/api/v1/local-agent/nodes/{config['node_id']}/heartbeat",
        {
            "agent_version": AGENT_VERSION,
            "capabilities": capabilities,
            "health": health,
        },
        agent_token=config["device_token"],
    )


def run(args: argparse.Namespace) -> None:
    config = _read_config(args.config)
    while True:
        response = heartbeat(config)
        print(
            json.dumps(
                {
                    "online": response["online"],
                    "node_id": response["id"],
                    "last_seen_at": response["last_seen_at"],
                    "execution_mode": response["execution_mode"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if args.once:
            return
        time.sleep(max(args.interval_seconds, 5))


def main() -> None:
    parser = argparse.ArgumentParser(description="春秋元泉 GEO Local Agent")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)

    enroll_parser = subparsers.add_parser("enroll", help="Use a one-time enrollment token")
    enroll_parser.add_argument("--server", required=True)
    enroll_parser.add_argument("--token", required=True)
    enroll_parser.add_argument("--name")
    enroll_parser.set_defaults(handler=enroll)

    run_parser = subparsers.add_parser("run", help="Report non-secret Local Agent health")
    run_parser.add_argument("--once", action="store_true")
    run_parser.add_argument("--interval-seconds", type=float, default=15)
    run_parser.set_defaults(handler=run)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
