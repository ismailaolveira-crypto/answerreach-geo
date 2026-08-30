"""Encrypt and authenticate deployment backups without exposing key material.

File format: magic (16 bytes), nonce (12 bytes), ciphertext, GCM tag (16 bytes).
The 32-byte key is supplied as a mounted file and is never printed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"CQYQ-GEO-BKP-v1\0"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024


def _read_key(path: Path) -> bytes:
    raw = path.read_text(encoding="ascii").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise SystemExit("backup key is not valid hexadecimal") from exc
    if len(key) != 32:
        raise SystemExit("backup key must contain exactly 32 bytes")
    return key


def encrypt(source: Path, destination: Path, key: bytes) -> None:
    nonce = os.urandom(NONCE_BYTES)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    encryptor = cipher.encryptor()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".geo-backup-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as incoming:
            target.write(MAGIC)
            target.write(nonce)
            while chunk := incoming.read(CHUNK_BYTES):
                target.write(encryptor.update(chunk))
            target.write(encryptor.finalize())
            target.write(encryptor.tag)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def decrypt(source: Path, destination: Path | None, key: bytes) -> None:
    size = source.stat().st_size
    header_size = len(MAGIC) + NONCE_BYTES
    if size <= header_size + TAG_BYTES:
        raise SystemExit("backup file is truncated")
    with source.open("rb") as incoming:
        if incoming.read(len(MAGIC)) != MAGIC:
            raise SystemExit("backup format is not recognized")
        nonce = incoming.read(NONCE_BYTES)
        incoming.seek(-TAG_BYTES, os.SEEK_END)
        tag = incoming.read(TAG_BYTES)
        remaining = size - header_size - TAG_BYTES
        incoming.seek(header_size)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        if destination is None:
            while remaining:
                chunk = incoming.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise SystemExit("backup file is truncated")
                remaining -= len(chunk)
                decryptor.update(chunk)
            decryptor.finalize()
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".geo-restore-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as target:
                while remaining:
                    chunk = incoming.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise SystemExit("backup file is truncated")
                    remaining -= len(chunk)
                    target.write(decryptor.update(chunk))
                target.write(decryptor.finalize())
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, destination)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("encrypt", "verify", "decrypt"))
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="After encryption, authenticate the output and remove the exact input file.",
    )
    args = parser.parse_args()
    key = _read_key(args.key_file)
    if args.mode == "encrypt":
        if args.output is None:
            parser.error("encrypt requires --output")
        encrypt(args.input, args.output, key)
        if args.delete_source:
            decrypt(args.output, None, key)
            args.input.unlink()
    elif args.mode == "decrypt":
        if args.output is None:
            parser.error("decrypt requires --output")
        decrypt(args.input, args.output, key)
    else:
        decrypt(args.input, None, key)


if __name__ == "__main__":
    main()
