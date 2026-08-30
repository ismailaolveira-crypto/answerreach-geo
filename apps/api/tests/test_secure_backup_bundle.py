from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from scripts.secure_backup_bundle import decrypt, encrypt, main


def test_backup_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    key = bytes.fromhex("42" * 32)
    source = tmp_path / "source.tar.gz"
    encrypted = tmp_path / "backup.gcm"
    restored = tmp_path / "restored.tar.gz"
    source.write_bytes((b"real backup data\0" * 100_000) + b"end")

    encrypt(source, encrypted, key)
    assert encrypted.read_bytes() != source.read_bytes()
    decrypt(encrypted, None, key)
    decrypt(encrypted, restored, key)
    assert restored.read_bytes() == source.read_bytes()

    tampered = bytearray(encrypted.read_bytes())
    tampered[len(tampered) // 2] ^= 1
    encrypted.write_bytes(tampered)
    with pytest.raises(InvalidTag):
        decrypt(encrypted, None, key)


def test_cli_can_remove_only_the_authenticated_plaintext_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "plaintext.tar.gz"
    encrypted = tmp_path / "backup.gcm"
    key_file = tmp_path / "key"
    source.write_bytes(b"private material")
    key_file.write_text("ab" * 32, encoding="ascii")
    monkeypatch.setattr(
        "sys.argv",
        [
            "secure_backup_bundle.py",
            "encrypt",
            "--key-file",
            str(key_file),
            "--input",
            str(source),
            "--output",
            str(encrypted),
            "--delete-source",
        ],
    )
    main()
    assert encrypted.is_file()
    assert not source.exists()
