"""Install and run a private shell decryptor that survives tool removal.

The installed copy imports only files in its own runtime directory. It does not
depend on the Envman tool environment after installation.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import sys
import tempfile
from importlib.metadata import version as package_version
from pathlib import Path


MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z", re.ASCII)


def _xdg_home(name: str, fallback: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return fallback
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path


def _installed_main() -> int:
    shell_protocol = sys.argv[1:] == ["--shell-protocol"]
    if sys.argv[1:] and not shell_protocol:
        return 1
    runtime_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(runtime_dir))
    from _secure_store import (  # type: ignore[import-not-found]
        SecureStoreError,
        decrypt_document,
        is_encrypted_document,
        load_or_create_file_key,
        safe_read,
    )

    try:
        home = Path.home()
        config_home = _xdg_home("XDG_CONFIG_HOME", home / ".config")
        state_home = _xdg_home("XDG_STATE_HOME", home / ".local" / "state")
        data_path = config_home / "envman" / "environment.conf"
        if not data_path.exists() and not data_path.is_symlink():
            return 0
        encrypted = safe_read(data_path, MAX_DOCUMENT_BYTES)
        if is_encrypted_document(encrypted):
            key = load_or_create_file_key(state_home / "envman" / "storage.key", create=False)
            plaintext = decrypt_document(encrypted, key)
        else:
            key_path = state_home / "envman" / "storage.key"
            if key_path.exists() or key_path.is_symlink():
                raise ValueError("plaintext storage with an existing key")
            plaintext = encrypted
        lines = [
            line[:-1] if line.endswith("\r") else line
            for line in plaintext.decode("utf-8").split("\n")
        ]
        assignments: list[bytes] = []
        seen: set[str] = set()
        for line in lines:
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("invalid assignment")
            name, value = line.split("=", 1)
            if not _NAME.fullmatch(name) or name in seen or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("invalid assignment")
            seen.add(name)
            assignments.append((line + "\n").encode("utf-8"))
        sys.stdout.buffer.write((b"ENVMAN-OK\n" if shell_protocol else b"") + b"".join(assignments))
        return 0
    except (OSError, UnicodeError, ValueError, SecureStoreError):
        print("envman: could not unlock or validate managed environment", file=sys.stderr)
        return 1


def install_retained_runtime(utility_dir: Path) -> Path:
    """Install a complete private loader under the Envman config directory."""
    import _cffi_backend
    import cffi
    import cryptography
    import pycparser

    if utility_dir.is_symlink():
        raise OSError(f"Unsafe retained loader directory: {utility_dir}")
    root_metadata = utility_dir.stat()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.getuid()
        or stat.S_IMODE(root_metadata.st_mode) != 0o700
    ):
        raise OSError(f"Unsafe retained loader directory: {utility_dir}")
    source_loader = Path(__file__)
    source_store = source_loader.with_name("_secure_store.py")
    source_crypto = Path(cryptography.__file__).parent
    site_packages = source_crypto.parent
    packages = (
        ("cryptography", source_crypto, cryptography.__version__),
        ("cffi", Path(cffi.__file__).parent, package_version("cffi")),
        ("pycparser", Path(pycparser.__file__).parent, package_version("pycparser")),
    )
    metadata_sources = tuple(
        site_packages / f"{name}-{version}.dist-info"
        for name, _, version in packages
    )
    if any(not metadata.is_dir() for metadata in metadata_sources):
        raise OSError("Retained loader dependency licenses or metadata are missing")
    backend = Path(_cffi_backend.__file__)
    if not backend.is_file():
        raise OSError("Retained loader CFFI backend is missing")
    release = hashlib.sha256(
        source_loader.read_bytes()
        + source_store.read_bytes()
        + "|".join(version for _, _, version in packages).encode("ascii")
    ).hexdigest()[:20]
    destination = utility_dir / f"loader-runtime-{release}"
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise OSError(f"Unsafe retained loader runtime: {destination}")
        metadata = destination.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise OSError(f"Unsafe retained loader runtime: {destination}")
        for name in (
            "_retained_loader.py",
            "_secure_store.py",
            "cryptography/__init__.py",
            "cffi/__init__.py",
            "pycparser/__init__.py",
            backend.name,
        ):
            if not (destination / name).is_file() or (destination / name).is_symlink():
                raise OSError(f"Incomplete retained loader runtime: {destination}")
        return destination / "_retained_loader.py"

    temporary = Path(tempfile.mkdtemp(prefix=".loader-runtime-", dir=utility_dir))
    try:
        shutil.copyfile(source_loader, temporary / "_retained_loader.py", follow_symlinks=False)
        shutil.copyfile(source_store, temporary / "_secure_store.py", follow_symlinks=False)
        for name, package, _ in packages:
            shutil.copytree(
                package,
                temporary / name,
                symlinks=False,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
        for metadata in metadata_sources:
            shutil.copytree(metadata, temporary / metadata.name, symlinks=False)
        shutil.copyfile(backend, temporary / backend.name, follow_symlinks=False)
        created = list(temporary.rglob("*"))
        for path in created:
            if path.is_symlink():
                raise OSError(f"Unsafe symlink in retained loader runtime: {path}")
            path.chmod(0o700 if path.is_dir() else 0o600)
            if path.is_file():
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        temporary.chmod(0o700)
        for directory in sorted(
            (temporary, *(path for path in created if path.is_dir())),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        try:
            temporary.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
        descriptor = os.open(utility_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return destination / "_retained_loader.py"
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    raise SystemExit(_installed_main())
