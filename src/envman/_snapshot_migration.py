"""Explicit, bounded conversion of legacy plaintext environment snapshots."""

from __future__ import annotations

import io
import os
import stat
import tarfile
import zlib
from pathlib import Path

from ._secure_store import (
    MAX_ENVELOPE_BYTES,
    PRIVATE_DIRECTORY_MODE,
    SecureStoreError,
    atomic_write_private,
    decrypt_document,
    encrypt_document,
    is_encrypted_document,
)


MAX_SNAPSHOT_ARCHIVE_BYTES = MAX_ENVELOPE_BYTES * 2
MAX_UNCOMPRESSED_TAR_BYTES = MAX_ENVELOPE_BYTES * 2
SNAPSHOT_MEMBER_NAME = "environment.conf"
_ARCHIVE_PREFIX = "environment.conf."
_ARCHIVE_SUFFIX = ".tar.gz"
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _raise_storage_error(message: str) -> None:
    raise SecureStoreError(message)


def _open_backup_directory(backup_dir: Path) -> int | None:
    if _DIRECTORY == 0 or _NOFOLLOW == 0:
        _raise_storage_error("Secure snapshot filesystem operations are unavailable.")
    try:
        descriptor = os.open(
            Path(backup_dir),
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
        )
    except FileNotFoundError:
        try:
            os.stat(Path(backup_dir), follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError:
            _raise_storage_error("Cannot safely inspect snapshot directory.")
        _raise_storage_error("Snapshot path is not a safe directory.")
    except OSError:
        _raise_storage_error("Cannot safely access snapshot directory.")

    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE
        ):
            _raise_storage_error("Snapshot directory permissions are unsafe.")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _is_snapshot_name(name: str) -> bool:
    return name.startswith(_ARCHIVE_PREFIX) and name.endswith(_ARCHIVE_SUFFIX)


def _read_archive(directory_fd: int, name: str) -> bytes:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            _raise_storage_error("Snapshot archive permissions are unsafe.")
        if metadata.st_size > MAX_SNAPSHOT_ARCHIVE_BYTES:
            _raise_storage_error("Snapshot archive exceeds the size limit.")

        chunks = bytearray()
        while len(chunks) <= MAX_SNAPSHOT_ARCHIVE_BYTES:
            part = os.read(
                descriptor,
                min(64 * 1024, MAX_SNAPSHOT_ARCHIVE_BYTES + 1 - len(chunks)),
            )
            if not part:
                break
            chunks.extend(part)
        if len(chunks) > MAX_SNAPSHOT_ARCHIVE_BYTES:
            _raise_storage_error("Snapshot archive exceeds the size limit.")
        return bytes(chunks)
    except SecureStoreError:
        raise
    except OSError:
        _raise_storage_error("Cannot safely read snapshot archive.")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _decompress_tar(archive: bytes) -> bytes:
    try:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        output = bytearray()
        pending = archive
        while pending:
            room = MAX_UNCOMPRESSED_TAR_BYTES + 1 - len(output)
            if room <= 0:
                _raise_storage_error("Snapshot tar exceeds the size limit.")
            output.extend(decompressor.decompress(pending, room))
            if len(output) > MAX_UNCOMPRESSED_TAR_BYTES:
                _raise_storage_error("Snapshot tar exceeds the size limit.")
            pending = decompressor.unconsumed_tail
            if pending and len(output) == MAX_UNCOMPRESSED_TAR_BYTES:
                _raise_storage_error("Snapshot tar exceeds the size limit.")
        if not decompressor.eof or decompressor.unused_data:
            _raise_storage_error("Snapshot gzip data is malformed.")
        output.extend(decompressor.flush(MAX_UNCOMPRESSED_TAR_BYTES + 1 - len(output)))
        if len(output) > MAX_UNCOMPRESSED_TAR_BYTES:
            _raise_storage_error("Snapshot tar exceeds the size limit.")
        return bytes(output)
    except SecureStoreError:
        raise
    except (zlib.error, ValueError):
        _raise_storage_error("Snapshot gzip data is malformed.")


def _read_environment_member(archive: bytes) -> tuple[bytes, float]:
    raw_tar = _decompress_tar(archive)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as bundle:
            members = bundle.getmembers()
            if len(members) != 1:
                _raise_storage_error("Snapshot archive must contain one member.")
            member = members[0]
            if (
                member.name != SNAPSHOT_MEMBER_NAME
                or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                or member.size < 0
                or member.size > MAX_ENVELOPE_BYTES
            ):
                _raise_storage_error("Snapshot archive member is unsafe.")
            stream = bundle.extractfile(member)
            if stream is None:
                _raise_storage_error("Snapshot archive member cannot be read.")
            contents = stream.read(MAX_ENVELOPE_BYTES + 1)
            if len(contents) != member.size:
                _raise_storage_error("Snapshot archive member is malformed.")
            return contents, member.mtime
    except SecureStoreError:
        raise
    except (EOFError, OSError, tarfile.TarError, ValueError):
        _raise_storage_error("Snapshot archive is malformed.")


def _inspect_archives(directory_fd: int) -> tuple[list[str], int]:
    plaintext_names: list[str] = []
    count = 0
    try:
        names = sorted(name for name in os.listdir(directory_fd) if _is_snapshot_name(name))
    except OSError:
        _raise_storage_error("Cannot list snapshot directory.")
    for name in names:
        archive = _read_archive(directory_fd, name)
        contents, _ = _read_environment_member(archive)
        if not is_encrypted_document(contents):
            count += 1
            plaintext_names.append(name)
    return plaintext_names, count


def inspect_legacy_snapshots(backup_dir: Path) -> int:
    """Count valid plaintext environment snapshots without changing any files."""
    directory_fd = _open_backup_directory(Path(backup_dir))
    if directory_fd is None:
        return 0
    try:
        _, count = _inspect_archives(directory_fd)
        return count
    finally:
        os.close(directory_fd)


def _build_encrypted_archive(contents: bytes, mtime: float, key: bytes) -> bytes:
    envelope = encrypt_document(contents, key)
    if decrypt_document(envelope, key) != contents:
        _raise_storage_error("Snapshot encryption verification failed.")
    output = io.BytesIO()
    try:
        with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.USTAR_FORMAT) as bundle:
            member = tarfile.TarInfo(SNAPSHOT_MEMBER_NAME)
            member.size = len(envelope)
            member.mode = 0o600
            member.mtime = mtime
            bundle.addfile(member, io.BytesIO(envelope))
    except (OSError, tarfile.TarError, ValueError):
        _raise_storage_error("Cannot rebuild snapshot archive.")
    result = output.getvalue()
    if len(result) > MAX_SNAPSHOT_ARCHIVE_BYTES:
        _raise_storage_error("Converted snapshot archive exceeds the size limit.")
    return result


def migrate_legacy_snapshots(backup_dir: Path, key: bytes) -> int:
    """Encrypt valid legacy environment snapshots in place; this is an explicit action."""
    # Validate the key before any possible replacement, including an empty archive set.
    encrypt_document(b"", key)
    directory_path = Path(backup_dir)
    directory_fd = _open_backup_directory(directory_path)
    if directory_fd is None:
        return 0
    try:
        plaintext_names, _ = _inspect_archives(directory_fd)
        # Check that every plaintext member can be encrypted and rebuilt before
        # replacing any archive, so invalid sizes or metadata cannot leave a
        # partially migrated snapshot set.
        for name in plaintext_names:
            original = _read_archive(directory_fd, name)
            contents, mtime = _read_environment_member(original)
            if not is_encrypted_document(contents):
                _build_encrypted_archive(contents, mtime, key)

        migrated = 0
        for name in plaintext_names:
            original = _read_archive(directory_fd, name)
            contents, mtime = _read_environment_member(original)
            if is_encrypted_document(contents):
                continue
            converted = _build_encrypted_archive(contents, mtime, key)
            atomic_write_private(directory_path / name, converted)
            migrated += 1
        return migrated
    finally:
        os.close(directory_fd)
