from pathlib import Path

import pytest

from app.core.config import Settings
from scripts.generate_deployment_config import _validate_host, build_config_lines


def _keys(lines: list[str]) -> set[str]:
    return {line.split("=", 1)[0] for line in lines}


def test_cloud_config_contains_only_required_named_settings() -> None:
    lines = build_config_lines(
        mode="cloud",
        host="GEO.Example.com.",
        port=3000,
        concurrency=32,
    )
    assert _keys(lines) == {
        "GEO_AUTH_SECRET",
        "GEO_INTERNAL_PROXY_SECRET",
        "GEO_WORKER_CONCURRENCY",
        "GEO_WORKER_INSTANCE_ID",
        "GEO_DOMAIN",
        "GEO_POSTGRES_PASSWORD",
    }
    assert "GEO_DOMAIN=geo.example.com" in lines


@pytest.mark.parametrize(
    "host",
    ["https://geo.example.com", "geo.example.com:443", "localhost", "192.168.1.10", "bad domain"],
)
def test_cloud_config_rejects_values_that_cannot_receive_public_tls(host: str) -> None:
    with pytest.raises(SystemExit):
        _validate_host("cloud", host)


def test_cloud_deployment_contract_requires_production_controls() -> None:
    Settings(
        _env_file=None,
        environment="production",
        deployment_mode="cloud",
        database_url="postgresql+psycopg://geo:password@postgres/geo",
        auto_create_tables=False,
        auth_secret="a" * 32,
        internal_proxy_secret="p" * 32,
        public_registration_enabled=False,
        cors_origins="https://geo.example.com",
        allowed_hosts="geo.example.com,api",
    ).validate_deployment()


def test_generated_config_is_created_with_private_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The CLI write path is covered without reading or printing any generated secret value.
    output = tmp_path / ".env.cloud"
    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_deployment_config.py",
            "--mode",
            "cloud",
            "--host",
            "geo.example.com",
            "--output",
            str(output),
        ],
    )
    from scripts.generate_deployment_config import main

    main()
    assert output.exists()
    assert output.stat().st_mode & 0o777 == 0o600
