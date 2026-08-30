from pathlib import Path
import plistlib

from app.services import worker_service
from app.services.worker_service import CommandResult


def _write_plist(path: Path, working_directory: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": worker_service.WORKER_SERVICE_LABEL,
                "WorkingDirectory": str(working_directory),
            },
            handle,
        )


def test_worker_service_is_explicitly_unsupported_off_macos() -> None:
    status = worker_service.inspect_managed_worker_service(system_name="Linux")

    assert status.supported is False
    assert status.state == "unsupported"


def test_worker_service_refuses_another_repository(tmp_path, monkeypatch) -> None:
    plist_path = tmp_path / "worker.plist"
    _write_plist(plist_path, tmp_path / "another-repository" / "apps" / "api")
    monkeypatch.setattr(worker_service, "_service_plist_path", lambda: plist_path)

    status = worker_service.inspect_managed_worker_service(
        system_name="Darwin",
        runner=lambda _args, _timeout: CommandResult(0, "state = running\npid = 99\n"),
    )

    assert status.state == "repository_conflict"
    assert status.repository_match is False


def test_repair_uses_only_the_fixed_install_script(tmp_path, monkeypatch) -> None:
    plist_path = tmp_path / "worker.plist"
    monkeypatch.setattr(worker_service, "_service_plist_path", lambda: plist_path)
    calls: list[tuple[str, ...]] = []
    installed = False

    def runner(args, _timeout) -> CommandResult:
        nonlocal installed
        calls.append(tuple(args))
        if args[:2] == ["/bin/launchctl", "print"]:
            return CommandResult(
                0 if installed else 113,
                "state = running\npid = 707\n" if installed else "",
            )
        assert list(args) == [
            "/bin/bash",
            str(worker_service.WORKER_INSTALL_SCRIPT),
        ]
        _write_plist(plist_path, worker_service.EXPECTED_API_DIR)
        installed = True
        return CommandResult(0, "installed")

    result = worker_service.repair_managed_worker_service(
        system_name="Darwin", runner=runner
    )

    assert result.action == "installed"
    assert result.status.running is True
    assert calls[1] == ("/bin/bash", str(worker_service.WORKER_INSTALL_SCRIPT))


def test_worker_service_layout_supports_flattened_api_container(tmp_path) -> None:
    source_file = tmp_path / "app" / "services" / "worker_service.py"
    source_file.parent.mkdir(parents=True)
    source_file.touch()
    project_root, api_directory = worker_service._resolve_project_layout(source_file)
    assert project_root == tmp_path
    assert api_directory == tmp_path
