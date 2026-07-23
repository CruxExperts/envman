"""Verified GitHub-release installation and update protocol for Envman.

This module intentionally uses only the standard library because the committed
``install.py`` is generated directly from it and runs through ``uv --script``.
All network, process, state, and clock boundaries are injectable for tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as host_platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

PRODUCT = "envman"
REPOSITORY = "CruxExperts/envman"
MANIFEST_SCHEMA = "envman.release-manifest"
RECEIPT_SCHEMA = "envman.install-receipt"
SCHEMA_VERSION = 1
MANIFEST_LIMIT = 1 * 1024 * 1024
CONSTRAINTS_LIMIT = 1 * 1024 * 1024
WHEEL_LIMIT = 20 * 1024 * 1024
SKILL_LIMIT = 1 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
LATEST_MANIFEST_URL = "https://github.com/CruxExperts/envman/releases/latest/download/release-manifest-v2.json"
INSTALLER_VERSION = "0.1.6"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UV_VERSION = re.compile(r"\buv\s+(\d+)\.(\d+)\.(\d+)\b", re.IGNORECASE)
DIST_INFO_NAME = re.compile(r"^envman-[^-]+\.dist-info/METADATA$")
SKILL_VERSION_MARKER = re.compile(r"(?m)^<!--\s*envman-skill-lock:\s*version=(?P<version>\d+\.\d+\.\d+)\s+source=src/envman/cli\.py\s*-->\s*$")
SUPPORTED_SKILL_ROOTS = (".agents/skills", ".codex/skills", ".claude/skills", ".cursor/skills", ".gemini/skills", ".opencode/skills")
SKILL_ASSET_FILENAME = "envman-environment-variable-manager-skill.md"
SKILL_DIRECTORY_NAME = "envman-environment-variable-manager"
SKILL_FILENAME = "SKILL.md"


class ReleaseProtocolError(RuntimeError):
    """A release asset, receipt, or runtime boundary is not trusted."""


@dataclass(frozen=True)
class Asset:
    filename: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    manifest_url: str
    wheel: Asset
    constraints: Asset
    python: str
    platform: str
    uv: str
    skill: Asset | None = None


@dataclass(frozen=True)
class InstallReceipt:
    installed_version: str
    provider: str
    repository: str
    manifest_url: str
    wheel: Asset
    constraints: Asset
    installer_version: str
    uv_version: str
    installed_at: str


Transport = Callable[[str, int], bytes]
Runner = Callable[[Sequence[str]], str]


def _parse_semver(value: object, label: str = "version") -> tuple[int, int, int]:
    if not isinstance(value, str) or not (match := SEMVER.fullmatch(value)):
        raise ReleaseProtocolError(f"{label} must be strict MAJOR.MINOR.PATCH SemVer.")
    return tuple(int(component) for component in match.groups())


def _expect_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ReleaseProtocolError(f"{label} must be an object.")
    return value


def _basename(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."}:
        raise ReleaseProtocolError(f"{label} must be a non-empty basename.")
    return value


def _release_base(version: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/v{version}/"


def _asset(value: object, version: str, label: str, maximum_size: int) -> Asset:
    payload = _expect_mapping(value, label)
    filename = _basename(payload.get("filename"), f"{label}.filename")
    expected_url = _release_base(version) + filename
    url = payload.get("url")
    if url != expected_url:
        raise ReleaseProtocolError(f"{label}.url must equal its immutable GitHub release asset URL.")
    digest = payload.get("sha256")
    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
        raise ReleaseProtocolError(f"{label}.sha256 must be lowercase SHA-256.")
    size = payload.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= maximum_size:
        raise ReleaseProtocolError(f"{label}.size exceeds the accepted limit.")
    return Asset(filename=filename, url=url, sha256=digest, size=size)


def parse_manifest(raw: bytes, *, manifest_url: str = LATEST_MANIFEST_URL) -> ReleaseManifest:
    """Parse a bounded release manifest, accepting the optional skill asset."""
    if len(raw) > MANIFEST_LIMIT:
        raise ReleaseProtocolError("Release manifest exceeds 1 MiB.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseProtocolError("Release manifest is not valid UTF-8 JSON.") from exc
    document = _expect_mapping(payload, "release manifest")
    expected = {"schema", "schema_version", "version", "repository", "compatibility", "assets"}
    if set(document) != expected:
        raise ReleaseProtocolError("Release manifest has an unexpected schema.")
    if document["schema"] != MANIFEST_SCHEMA or document["schema_version"] != SCHEMA_VERSION:
        raise ReleaseProtocolError("Release manifest schema is unsupported.")
    if document["repository"] != REPOSITORY:
        raise ReleaseProtocolError("Release manifest repository is not trusted.")
    version_value = document["version"]
    _parse_semver(version_value)
    assert isinstance(version_value, str)
    compatibility = _expect_mapping(document["compatibility"], "compatibility")
    if set(compatibility) != {"python", "platform", "uv"}:
        raise ReleaseProtocolError("Release compatibility fields are incomplete.")
    python_spec = compatibility["python"]
    platform_spec = compatibility["platform"]
    uv_spec = compatibility["uv"]
    if python_spec != ">=3.12,<3.13" or platform_spec != "linux-x86_64" or uv_spec != ">=0.11,<0.12":
        raise ReleaseProtocolError("Release compatibility is unsupported.")
    assets = _expect_mapping(document["assets"], "assets")
    if not {"wheel", "runtime_constraints"} <= set(assets) or set(assets) - {"wheel", "runtime_constraints", "skill"}:
        raise ReleaseProtocolError("Release manifest must contain one wheel and one constraints file.")
    wheel = _asset(assets["wheel"], version_value, "wheel", WHEEL_LIMIT)
    constraints = _asset(assets["runtime_constraints"], version_value, "runtime_constraints", CONSTRAINTS_LIMIT)
    if not wheel.filename.endswith(".whl") or constraints.filename != "runtime-constraints.txt":
        raise ReleaseProtocolError("Release asset filenames are invalid.")
    skill = None
    if "skill" in assets:
        skill = _asset(assets["skill"], version_value, "skill", SKILL_LIMIT)
        if skill.filename != SKILL_ASSET_FILENAME:
            raise ReleaseProtocolError("Skill asset filename is invalid.")
    return ReleaseManifest(version_value, manifest_url, wheel, constraints, python_spec, platform_spec, uv_spec, skill)


def _redirect_host(url: str, *, initial: bool = False) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise ReleaseProtocolError("Release URL must be HTTPS without credentials or a fragment.")
    if parsed.hostname not in {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}:
        raise ReleaseProtocolError("Release download host is not trusted.")
    if initial and (parsed.hostname != "github.com" or parsed.query):
        raise ReleaseProtocolError("Release source URL must be a plain GitHub HTTPS URL.")
    if parsed.query and parsed.hostname not in {"objects.githubusercontent.com", "release-assets.githubusercontent.com"}:
        raise ReleaseProtocolError("Only signed GitHub release-asset redirects may include query parameters.")
    return parsed.hostname


def default_transport(url: str, limit: int) -> bytes:
    """Download one bounded asset while accepting only GitHub-controlled redirects."""
    _redirect_host(url, initial=True)

    class GuardedRedirect(HTTPRedirectHandler):
        def redirect_request(self, request: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:
            _redirect_host(newurl)
            return super().redirect_request(request, fp, code, msg, headers, newurl)

    request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "envman-installer/0.1"})
    try:
        with build_opener(GuardedRedirect()).open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            _redirect_host(response.geturl())
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdigit() or int(declared) > limit):
                raise ReleaseProtocolError("Release asset is larger than its allowed limit.")
            body = response.read(limit + 1)
    except ReleaseProtocolError:
        raise
    except OSError as exc:
        raise ReleaseProtocolError(f"Could not download release asset: {exc}") from exc
    if len(body) > limit:
        raise ReleaseProtocolError("Release asset is larger than its allowed limit.")
    return body


def download_asset(asset: Asset, *, transport: Transport = default_transport, maximum_size: int) -> bytes:
    if asset.size > maximum_size:
        raise ReleaseProtocolError("Manifest asset exceeds its accepted class limit.")
    body = transport(asset.url, maximum_size)
    if len(body) != asset.size:
        raise ReleaseProtocolError("Release asset size does not match its manifest.")
    if hashlib.sha256(body).hexdigest() != asset.sha256:
        raise ReleaseProtocolError("Release asset SHA-256 does not match its manifest.")
    return body


def validate_constraints(raw: bytes) -> None:
    """Accept a small, fully pinned, index-resolved runtime constraints projection."""
    if len(raw) > CONSTRAINTS_LIMIT:
        raise ReleaseProtocolError("Runtime constraints exceed 1 MiB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseProtocolError("Runtime constraints must be UTF-8.") from exc
    pinned = re.compile(r"^[A-Za-z0-9_.-]+==[A-Za-z0-9_.!+-]+$")
    seen: set[str] = set()
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if not pinned.fullmatch(candidate):
            raise ReleaseProtocolError("Runtime constraints must contain only exact package pins.")
        name = candidate.split("==", 1)[0].lower().replace("_", "-")
        if name in seen:
            raise ReleaseProtocolError("Runtime constraints contain duplicate package pins.")
        seen.add(name)
    if "cryptography" not in seen:
        raise ReleaseProtocolError("Runtime constraints must include cryptography.")


def validate_skill(raw: bytes, version: str) -> str:
    """Validate and decode the generated skill before it can be installed."""
    if len(raw) > SKILL_LIMIT:
        raise ReleaseProtocolError("Envman agent skill exceeds 1 MiB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseProtocolError("Envman agent skill must be UTF-8.") from exc
    marker = SKILL_VERSION_MARKER.search(text)
    if marker is None:
        raise ReleaseProtocolError("Envman agent skill is missing its authenticity marker.")
    if marker.group("version") != version:
        raise ReleaseProtocolError("Envman agent skill version does not match the release manifest.")
    return text


def discover_repo_root(cwd: Path | None = None) -> Path:
    """Find the nearest repository root, or use cwd when no .git exists."""
    candidate = Path(cwd or Path.cwd()).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(candidate))
    if not candidate.is_dir() or candidate.is_symlink():
        raise ReleaseProtocolError("Selected repository root must be a real directory.")
    for parent in (candidate, *candidate.parents):
        git_marker = parent / ".git"
        if git_marker.exists() or git_marker.is_symlink():
            return parent
    return candidate


def _assert_contained(root: Path, path: Path, label: str) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ReleaseProtocolError(f"{label} escapes the selected repository root.") from exc


def _reject_symlink_components(root: Path, path: Path, label: str) -> None:
    _assert_contained(root, path, label)
    relative = path.relative_to(root)
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ReleaseProtocolError(f"{label} contains an unsafe symlink.")


def _candidate_skill_roots(root: Path) -> list[Path]:
    found: list[Path] = []
    for relative in SUPPORTED_SKILL_ROOTS:
        candidate = root / relative
        if candidate.exists() or candidate.is_symlink():
            _reject_symlink_components(root, candidate, "Skill root")
            if not candidate.is_dir():
                raise ReleaseProtocolError(f"Skill root is not a directory: {candidate}")
            found.append(candidate)
    if not found:
        found.append(root / ".agents" / "skills")
    return found


def skill_install_targets(repo_root: Path | None = None) -> list[Path]:
    """Return all supported existing roots, creating .agents/skills if needed."""
    root = discover_repo_root(repo_root)
    found = _candidate_skill_roots(root)
    if len(found) == 1 and not found[0].exists():
        candidate = found[0]
        _reject_symlink_components(root, candidate, "Skill root")
        try:
            candidate.mkdir(mode=0o755, parents=True, exist_ok=True)
        except OSError as exc:
            raise ReleaseProtocolError(f"Skill root is not a directory: {candidate}") from exc
        if candidate.is_symlink() or not candidate.is_dir():
            raise ReleaseProtocolError(f"Skill root is unsafe: {candidate}")
    return found


def _validated_skill_destinations(root: Path, roots: Sequence[Path]) -> list[Path]:
    destinations: list[Path] = []
    for skill_root in roots:
        destination_dir = skill_root / SKILL_DIRECTORY_NAME
        destination = destination_dir / SKILL_FILENAME
        _reject_symlink_components(root, destination_dir, "Skill destination")
        if destination_dir.exists() and not destination_dir.is_dir():
            raise ReleaseProtocolError(f"Skill destination is not a directory: {destination_dir}")
        if destination.is_symlink():
            raise ReleaseProtocolError("Skill destination must not be a symlink.")
        if destination.exists() and not _marked_skill(destination):
            raise ReleaseProtocolError(f"Refusing to replace an unmarked skill: {destination_dir}")
        destinations.append(destination)
    return destinations


def _skill_snapshot(root: Path, destinations: Sequence[Path]) -> dict[Path, tuple[str, bytes | None, int | None]]:
    paths: set[Path] = set()
    for destination in destinations:
        _reject_symlink_components(root, destination, "Skill snapshot")
        current = destination
        while current != root:
            paths.add(current)
            current = current.parent
    snapshot: dict[Path, tuple[str, bytes | None, int | None]] = {}
    for path in paths:
        _reject_symlink_components(root, path, "Skill snapshot")
        if path.is_symlink():
            raise ReleaseProtocolError("Skill snapshot contains an unsafe symlink.")
        elif path.is_file():
            snapshot[path] = ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        elif path.is_dir():
            snapshot[path] = ("dir", None, None)
        else:
            snapshot[path] = ("missing", None, None)
    return snapshot


def _restore_skill_snapshot(snapshot: Mapping[Path, tuple[str, bytes | None, int | None]]) -> None:
    for path, (kind, raw, mode) in sorted(snapshot.items(), key=lambda item: len(item[0].parts), reverse=True):
        if kind == "missing":
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        elif kind == "file":
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            assert raw is not None
            _atomic_skill_write(path, raw)
            assert mode is not None
            os.chmod(path, mode)
        elif kind == "dir" and not path.exists():
            path.mkdir(mode=0o755)


def install_skill_asset(
    raw: bytes,
    version: str,
    *,
    repo_root: Path | None = None,
    snapshot: Mapping[Path, tuple[str, bytes | None, int | None]] | None = None,
) -> list[Path]:
    """Install one verified skill asset into every safe supported repo-local root."""
    validate_skill(raw, version)
    root = discover_repo_root(repo_root)
    roots = _candidate_skill_roots(root)
    destinations = _validated_skill_destinations(root, roots)
    prior = snapshot or _skill_snapshot(root, destinations)
    skill_install_targets(root)
    try:
        for destination in destinations:
            try:
                destination.parent.mkdir(mode=0o755, parents=False, exist_ok=True)
            except OSError as exc:
                raise ReleaseProtocolError(f"Skill destination is not a directory: {destination.parent}") from exc
            _reject_symlink_components(root, destination.parent, "Skill destination")
            _atomic_skill_write(destination, raw)
    except Exception as install_error:
        try:
            _restore_skill_snapshot(prior)
        except Exception as rollback_error:
            raise ReleaseProtocolError(f"Skill installation failed and rollback failed: {rollback_error}") from install_error
        if isinstance(install_error, ReleaseProtocolError):
            raise
        raise ReleaseProtocolError(f"Skill installation failed: {install_error}") from install_error
    return destinations


def _marked_skill(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return SKILL_VERSION_MARKER.search(text) is not None


def _atomic_skill_write(destination: Path, raw: bytes) -> None:
    parent = destination.parent
    descriptor, temporary_name = tempfile.mkstemp(prefix=".envman-skill-", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o644)
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()




def validate_wheel(raw: bytes, version: str) -> None:
    """Verify the wheel archive without extracting untrusted members."""
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
            infos = archive.infolist()
            for info in infos:
                path = Path(info.filename)
                if info.filename.startswith(("/", "\\")) or ".." in path.parts or "\x00" in info.filename:
                    raise ReleaseProtocolError("Wheel contains an unsafe archive member.")
            metadata_names = [info.filename for info in infos if DIST_INFO_NAME.fullmatch(info.filename)]
            if len(metadata_names) != 1:
                raise ReleaseProtocolError("Wheel must contain exactly one Envman METADATA file.")
            metadata = archive.read(metadata_names[0]).decode("utf-8")
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ReleaseProtocolError("Release wheel is not a valid UTF-8 wheel archive.") from exc
    fields: dict[str, str] = {}
    for line in metadata.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields.setdefault(key.lower(), value.strip())
    normalized_name = fields.get("name", "").lower().replace("_", "-")
    if normalized_name != PRODUCT or fields.get("version") != version:
        raise ReleaseProtocolError("Wheel METADATA does not match the release manifest.")


def default_state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    return (Path(configured).expanduser() if configured else Path.home() / ".local" / "state") / PRODUCT


def receipt_path(state_root: Path | None = None) -> Path:
    return (state_root or default_state_root()) / "install.json"


def _ensure_private_directory(directory: Path) -> None:
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir():
            raise ReleaseProtocolError(f"State directory is unsafe: {directory}")
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseProtocolError(f"State directory is unsafe: {directory}")


def _asset_from_mapping(value: object, label: str) -> Asset:
    payload = _expect_mapping(value, label)
    filename = _basename(payload.get("filename"), f"{label}.filename")
    url = payload.get("url")
    digest = payload.get("sha256")
    size = payload.get("size")
    if not isinstance(url, str) or not isinstance(digest, str) or SHA256.fullmatch(digest) is None or not isinstance(size, int):
        raise ReleaseProtocolError(f"{label} is invalid.")
    return Asset(filename, url, digest, size)


def read_receipt(path: Path | None = None) -> InstallReceipt:
    candidate = path or receipt_path()
    if candidate.is_symlink():
        raise ReleaseProtocolError("Install receipt must not be a symlink.")
    try:
        raw = candidate.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseProtocolError("No Envman installation receipt exists.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseProtocolError("Install receipt is unreadable.") from exc
    document = _expect_mapping(payload, "install receipt")
    expected = {"schema", "schema_version", "installed_version", "provider", "repository", "manifest_url", "wheel", "constraints", "installer_version", "uv_version", "installed_at"}
    if set(document) != expected or document["schema"] != RECEIPT_SCHEMA or document["schema_version"] != SCHEMA_VERSION:
        raise ReleaseProtocolError("Install receipt schema is unsupported.")
    if document["provider"] != "github-release-wheel" or document["repository"] != REPOSITORY:
        raise ReleaseProtocolError("Install receipt provider is not trusted.")
    installed_version = document["installed_version"]
    _parse_semver(installed_version, "installed_version")
    for field in ("manifest_url", "installer_version", "uv_version", "installed_at"):
        if not isinstance(document[field], str) or not document[field]:
            raise ReleaseProtocolError(f"Install receipt {field} is invalid.")
    assert isinstance(installed_version, str)
    return InstallReceipt(installed_version, "github-release-wheel", REPOSITORY, document["manifest_url"], _asset_from_mapping(document["wheel"], "wheel"), _asset_from_mapping(document["constraints"], "constraints"), document["installer_version"], document["uv_version"], document["installed_at"])


def write_receipt(receipt: InstallReceipt, path: Path | None = None) -> None:
    destination = path or receipt_path()
    _ensure_private_directory(destination.parent)
    if destination.exists() and destination.is_symlink():
        raise ReleaseProtocolError("Install receipt must not replace a symlink.")
    document = {
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        **asdict(receipt),
    }
    encoded = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".install-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        directory_descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def default_runner(argv: Sequence[str]) -> str:
    completed = subprocess.run(list(argv), check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return completed.stdout


def verify_runtime(*, runner: Runner = default_runner, system: str | None = None, machine: str | None = None, python_info: tuple[int, int] | None = None, uv_executable: str = "uv") -> str:
    effective_system = (system or host_platform.system()).lower()
    effective_machine = (machine or host_platform.machine()).lower()
    effective_python = python_info or sys.version_info[:2]
    if effective_system != "linux" or effective_machine not in {"x86_64", "amd64"}:
        raise ReleaseProtocolError("Envman releases currently support Linux x86_64 only.")
    if not ((3, 12) <= effective_python < (3, 13)):
        raise ReleaseProtocolError("Envman releases require CPython >=3.12,<3.13.")
    try:
        output = runner([uv_executable, "--version"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseProtocolError("A compatible uv executable is required.") from exc
    if not (match := UV_VERSION.search(output)):
        raise ReleaseProtocolError("Could not determine the uv version.")
    version = tuple(int(component) for component in match.groups())
    if not ((0, 11, 0) <= version < (0, 12, 0)):
        raise ReleaseProtocolError("Envman releases require uv >=0.11,<0.12.")
    return ".".join(match.groups())


def _write_artifact(root: Path, filename: str, raw: bytes) -> Path:
    destination = root / filename
    destination.write_bytes(raw)
    return destination


def _tool_present(*, runner: Runner, uv_executable: str) -> bool:
    try:
        listing = runner([uv_executable, "tool", "list"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseProtocolError("Could not inspect the existing uv tool installation.") from exc
    return any(line.split(maxsplit=1)[0].lower().replace("_", "-") == PRODUCT for line in listing.splitlines() if line.strip())


def _verify_distribution_metadata(version: str, *, runner: Runner, uv_executable: str) -> None:
    """Require uv's installed-tool metadata to agree before publishing a receipt."""
    try:
        listing = runner([uv_executable, "tool", "list"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseProtocolError("Installed Envman metadata could not be verified.") from exc
    expected = re.compile(rf"^{PRODUCT}\s+(?:v)?{re.escape(version)}(?:\s|$)", re.IGNORECASE)
    if not any(expected.search(line) for line in listing.splitlines()):
        raise ReleaseProtocolError("Installed Envman metadata does not match the release manifest.")


def _install_argv(wheel: Path, constraints: Path, *, uv_executable: str = "uv") -> list[str]:
    return [uv_executable, "tool", "install", "--python", "3.12", "--force", "--no-build", "--constraints", str(constraints), str(wheel)]


def _verify_command(version: str, *, runner: Runner, uv_executable: str) -> None:
    try:
        bin_output = runner([uv_executable, "tool", "dir", "--bin"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseProtocolError("Installed Envman command location could not be determined.") from exc
    bin_lines = [line.strip() for line in bin_output.splitlines() if line.strip()]
    if len(bin_lines) != 1 or not Path(bin_lines[0]).is_absolute():
        raise ReleaseProtocolError("uv returned an invalid tool executable directory.")
    executable = str(Path(bin_lines[0]) / PRODUCT)
    try:
        output = runner([executable, "--version"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseProtocolError("Installed Envman command could not be verified.") from exc
    if output.strip() != f"{PRODUCT} {version}":
        raise ReleaseProtocolError("Installed Envman version does not match the release manifest.")


def _receipt(manifest: ReleaseManifest, uv_version: str, now: Callable[[], datetime]) -> InstallReceipt:
    return InstallReceipt(manifest.version, "github-release-wheel", REPOSITORY, manifest.manifest_url, manifest.wheel, manifest.constraints, INSTALLER_VERSION, uv_version, now().astimezone(UTC).isoformat().replace("+00:00", "Z"))


def install_manifest(manifest: ReleaseManifest, *, transport: Transport = default_transport, runner: Runner = default_runner, state_root: Path | None = None, uv_executable: str = "uv", now: Callable[[], datetime] = lambda: datetime.now(UTC), install_skill: bool = False, repo_root: Path | None = None) -> InstallReceipt:
    """Install one verified manifest, refusing to replace an unowned Envman tool."""
    if install_skill and manifest.skill is None:
        raise ReleaseProtocolError("This release does not contain an Envman agent skill asset.")
    uv_version = verify_runtime(runner=runner, uv_executable=uv_executable)
    receipt_file = receipt_path(state_root)
    previous: InstallReceipt | None = None
    present = _tool_present(runner=runner, uv_executable=uv_executable)
    if present:
        previous = read_receipt(receipt_file)
    elif receipt_file.exists():
        raise ReleaseProtocolError("A receipt exists but the Envman uv tool is absent.")
    wheel = download_asset(manifest.wheel, transport=transport, maximum_size=WHEEL_LIMIT)
    constraints = download_asset(manifest.constraints, transport=transport, maximum_size=CONSTRAINTS_LIMIT)
    validate_wheel(wheel, manifest.version)
    validate_constraints(constraints)
    skill: bytes | None = None
    skill_snapshot: Mapping[Path, tuple[str, bytes | None, int | None]] | None = None
    if install_skill:
        assert manifest.skill is not None
        skill = download_asset(manifest.skill, transport=transport, maximum_size=SKILL_LIMIT)
        validate_skill(skill, manifest.version)
        skill_root = discover_repo_root(repo_root)
        skill_snapshot = _skill_snapshot(skill_root, _validated_skill_destinations(skill_root, _candidate_skill_roots(skill_root)))
    root = Path(tempfile.mkdtemp(prefix="envman-release-"))
    try:
        wheel_path = _write_artifact(root, manifest.wheel.filename, wheel)
        constraints_path = _write_artifact(root, manifest.constraints.filename, constraints)
        if previous is not None:
            prior_wheel = download_asset(previous.wheel, transport=transport, maximum_size=WHEEL_LIMIT)
            prior_constraints = download_asset(previous.constraints, transport=transport, maximum_size=CONSTRAINTS_LIMIT)
            validate_wheel(prior_wheel, previous.installed_version)
            validate_constraints(prior_constraints)
            prior_wheel_path = _write_artifact(root, "previous-" + previous.wheel.filename, prior_wheel)
            prior_constraints_path = _write_artifact(root, "previous-" + previous.constraints.filename, prior_constraints)
        try:
            runner(_install_argv(wheel_path, constraints_path, uv_executable=uv_executable))
            _verify_distribution_metadata(manifest.version, runner=runner, uv_executable=uv_executable)
            _verify_command(manifest.version, runner=runner, uv_executable=uv_executable)
            if skill is not None:
                install_skill_asset(skill, manifest.version, repo_root=repo_root, snapshot=skill_snapshot)
            result = _receipt(manifest, uv_version, now)
            write_receipt(result, receipt_file)
            return result
        except Exception as install_error:
            rollback_failures: list[str] = []
            if skill_snapshot is not None:
                try:
                    _restore_skill_snapshot(skill_snapshot)
                except Exception as rollback_error:
                    rollback_failures.append(f"skill rollback: {rollback_error}")
            if previous is None:
                try:
                    runner([uv_executable, "tool", "uninstall", PRODUCT])
                except (OSError, subprocess.CalledProcessError) as rollback_error:
                    rollback_failures.append(f"tool rollback: {rollback_error}")
            else:
                try:
                    runner(_install_argv(prior_wheel_path, prior_constraints_path, uv_executable=uv_executable))
                    write_receipt(previous, receipt_file)
                except Exception as rollback_error:
                    rollback_failures.append(f"update rollback: {rollback_error}")
            if rollback_failures:
                raise ReleaseProtocolError(f"Installation failed and rollback failed: {'; '.join(rollback_failures)}") from install_error
            if isinstance(install_error, ReleaseProtocolError):
                raise
            raise ReleaseProtocolError(f"Installation failed: {install_error}") from install_error
    finally:
        shutil.rmtree(root, ignore_errors=True)


def load_manifest(url: str = LATEST_MANIFEST_URL, *, transport: Transport = default_transport) -> ReleaseManifest:
    return parse_manifest(transport(url, MANIFEST_LIMIT), manifest_url=url)


def update(*, check_only: bool, transport: Transport = default_transport, runner: Runner = default_runner, state_root: Path | None = None, uv_executable: str = "uv", now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict[str, object]:
    receipt = read_receipt(receipt_path(state_root))
    if receipt.provider != "github-release-wheel":
        raise ReleaseProtocolError("Install receipt provider is not supported for updates.")
    manifest = load_manifest(receipt.manifest_url, transport=transport)
    current = _parse_semver(receipt.installed_version, "installed_version")
    candidate = _parse_semver(manifest.version)
    if candidate < current:
        raise ReleaseProtocolError("Refusing a downgrade from the recorded installation.")
    if candidate == current:
        return {"schema": "envman.update-result", "schema_version": 1, "status": "current", "installed_version": receipt.installed_version, "available_version": manifest.version}
    if check_only:
        return {"schema": "envman.update-result", "schema_version": 1, "status": "update-available", "installed_version": receipt.installed_version, "available_version": manifest.version}
    installed = install_manifest(manifest, transport=transport, runner=runner, state_root=state_root, uv_executable=uv_executable, now=now)
    return {"schema": "envman.update-result", "schema_version": 1, "status": "updated", "installed_version": receipt.installed_version, "available_version": installed.installed_version}


def installer_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a verified Envman GitHub release into uv tools.")
    parser.add_argument("--manifest-url", default=LATEST_MANIFEST_URL)
    skill_group = parser.add_mutually_exclusive_group()
    skill_group.add_argument("--install-skill", action="store_true", dest="install_skill")
    skill_group.add_argument("--no-install-skill", action="store_false", dest="install_skill")
    parser.set_defaults(install_skill=None)
    arguments = parser.parse_args(argv)
    try:
        manifest = load_manifest(arguments.manifest_url)
        install_skill = arguments.install_skill
        if install_skill is None:
            if manifest.skill is None:
                install_skill = False
            elif sys.stdin.isatty() and sys.stdout.isatty():
                try:
                    answer = input("Install the Envman agent skill into this repository? [Y/n] ").strip().lower()
                except (EOFError, OSError):
                    answer = "n"
                install_skill = answer not in {"n", "no"}
            else:
                install_skill = False
        receipt = install_manifest(manifest, install_skill=install_skill, repo_root=Path.cwd())
    except ReleaseProtocolError as exc:
        print(f"envman installer: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": "envman.install-result", "schema_version": 1, "status": "installed", "version": receipt.installed_version}, sort_keys=True))
    return 0


