"""Small, fail-closed helpers for encrypted documents and private files."""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecureStoreError(Exception):
    """Raised when secure storage input or filesystem state is unsafe."""


MAX_ENVELOPE_BYTES = 8 * 1024 * 1024
KEY_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700
KEY_BYTES = 44
_DOCUMENT_MAGIC = b"ENVMAN\x00"
_DOCUMENT_VERSION = 1
_DOCUMENT_HEADER = _DOCUMENT_MAGIC + bytes((_DOCUMENT_VERSION,))
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def encrypt_document(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt bytes in a versioned, authenticated Fernet envelope."""
    if not isinstance(plaintext, bytes) or not isinstance(key, bytes):
        raise SecureStoreError("Document or key has an invalid type.")
    if len(plaintext) > MAX_ENVELOPE_BYTES:
        raise SecureStoreError("Encrypted document exceeds the size limit.")
    try:
        token = Fernet(key).encrypt(plaintext)
    except (TypeError, ValueError):
        raise SecureStoreError("Encryption key is invalid.") from None
    envelope = _DOCUMENT_HEADER + token
    if len(envelope) > MAX_ENVELOPE_BYTES:
        raise SecureStoreError("Encrypted document exceeds the size limit.")
    return envelope


def decrypt_document(envelope: bytes, key: bytes) -> bytes:
    """Authenticate and decrypt a complete versioned document envelope."""
    if not isinstance(envelope, bytes) or not isinstance(key, bytes):
        raise SecureStoreError("Document or key has an invalid type.")
    if len(envelope) > MAX_ENVELOPE_BYTES:
        raise SecureStoreError("Encrypted document exceeds the size limit.")
    if not envelope.startswith(_DOCUMENT_MAGIC):
        raise SecureStoreError("Document is not an encrypted envman document.")
    if not envelope.startswith(_DOCUMENT_HEADER):
        raise SecureStoreError("Encrypted document version is unsupported.")
    token = envelope[len(_DOCUMENT_HEADER) :]
    if not token:
        raise SecureStoreError("Encrypted document is malformed.")
    try:
        return Fernet(key).decrypt(token)
    except (InvalidToken, TypeError, ValueError):
        raise SecureStoreError("Encrypted document authentication failed.") from None


def is_encrypted_document(data: bytes) -> bool:
    """Return whether data carries the envman secure-document magic."""
    return isinstance(data, bytes) and data.startswith(_DOCUMENT_MAGIC)


def _require_nofollow() -> None:
    if _NOFOLLOW == 0 or _DIRECTORY == 0:
        raise SecureStoreError("Secure filesystem operations are unavailable.")


def _path_name(path: Path) -> str:
    name = Path(path).name
    if not name or name in (".", ".."):
        raise SecureStoreError("File path is invalid.")
    return name


def _open_directory(path: Path, *, create: bool = False, private: bool = False) -> int:
    _require_nofollow()
    directory = Path(path)
    descriptor: int | None = None
    try:
        if create:
            directory.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
        flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW
        descriptor = os.open(directory, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise SecureStoreError("Directory is not owned by the current user.")
        if private and create and stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
            os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
            metadata = os.fstat(descriptor)
        if private and stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
            raise SecureStoreError("Directory must have mode 0700.")
        result = descriptor
        descriptor = None
        return result
    except SecureStoreError:
        raise
    except OSError:
        raise SecureStoreError("Cannot safely access directory.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_key(raw_key: bytes) -> bytes:
    if len(raw_key) != KEY_BYTES:
        raise SecureStoreError("Encryption key file is malformed.")
    try:
        Fernet(raw_key)
    except (TypeError, ValueError):
        raise SecureStoreError("Encryption key file is malformed.") from None
    return raw_key


def _read_key_at(directory_fd: int, name: str) -> bytes:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != KEY_FILE_MODE
        ):
            raise SecureStoreError("Encryption key file permissions are unsafe.")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw_key = handle.read(KEY_BYTES + 1)
        return _validate_key(raw_key)
    except SecureStoreError:
        raise
    except OSError:
        raise SecureStoreError("Cannot safely read encryption key file.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_or_create_file_key(path: Path, create: bool) -> bytes:
    """Load a private Fernet key, or create one without replacing an existing file."""
    key_path = Path(path)
    name = _path_name(key_path)
    directory_fd = _open_directory(
        key_path.parent,
        create=create,
        private=True,
    )
    try:
        try:
            return _read_key_at(directory_fd, name)
        except SecureStoreError:
            # Only a genuinely missing destination may enter the creation path.
            if not create or not _is_missing_key(directory_fd, name):
                raise

        generated = Fernet.generate_key()
        descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
            descriptor = os.open(
                name,
                flags,
                KEY_FILE_MODE,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            return _read_key_at(directory_fd, name)
        except OSError:
            raise SecureStoreError("Cannot create encryption key file.") from None

        try:
            os.fchmod(descriptor, KEY_FILE_MODE)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise SecureStoreError("Created encryption key file is unsafe.")
            _write_all(descriptor, generated)
            os.fsync(descriptor)
        except SecureStoreError:
            raise
        except OSError:
            raise SecureStoreError("Cannot persist encryption key file.") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        try:
            os.fsync(directory_fd)
        except OSError:
            raise SecureStoreError("Cannot persist encryption key directory.") from None
        return generated
    finally:
        os.close(directory_fd)


def _is_missing_key(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def safe_read(
    path: Path,
    max_bytes: int,
    *,
    expected_mode: int | None = None,
) -> bytes:
    """Read an owned regular file without following links and within a size bound."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise SecureStoreError("Read size limit is invalid.")
    if expected_mode is not None and (
        not isinstance(expected_mode, int)
        or isinstance(expected_mode, bool)
        or expected_mode < 0
    ):
        raise SecureStoreError("Expected file mode is invalid.")
    file_path = Path(path)
    name = _path_name(file_path)
    directory_fd = _open_directory(file_path.parent)
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise SecureStoreError("File is not an owned regular file.")
        if expected_mode is not None and stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise SecureStoreError("File permissions do not match the required mode.")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            contents = handle.read(max_bytes + 1)
        if len(contents) > max_bytes:
            raise SecureStoreError("File exceeds the read size limit.")
        return contents
    except SecureStoreError:
        raise
    except OSError:
        raise SecureStoreError("Cannot safely read file.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _check_write_target(directory_fd: int, name: str) -> None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        raise SecureStoreError("Cannot safely inspect destination file.") from None
    if stat.S_ISLNK(metadata.st_mode):
        raise SecureStoreError("Refusing to write through a symlink.")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise SecureStoreError("Destination is not an owned regular file.")


def atomic_write_private(path: Path, content: bytes) -> None:
    """Atomically replace a file with private bytes in an owned mode-0700 directory."""
    if not isinstance(content, bytes):
        raise SecureStoreError("File contents have an invalid type.")
    file_path = Path(path)
    name = _path_name(file_path)
    directory_fd = _open_directory(file_path.parent, private=True)
    temporary_name: str | None = None
    descriptor: int | None = None
    try:
        _check_write_target(directory_fd, name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW
        for _ in range(16):
            candidate = f".envman-{secrets.token_hex(16)}.tmp"
            try:
                descriptor = os.open(
                    candidate,
                    flags,
                    KEY_FILE_MODE,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if descriptor is None or temporary_name is None:
            raise SecureStoreError("Cannot allocate private temporary file.")
        os.fchmod(descriptor, KEY_FILE_MODE)
        _write_all(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        _check_write_target(directory_fd, name)
        os.replace(
            temporary_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        os.fsync(directory_fd)
    except SecureStoreError:
        raise
    except OSError:
        raise SecureStoreError("Cannot safely write file.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        os.close(directory_fd)
