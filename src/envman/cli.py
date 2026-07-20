#!/usr/bin/env python3
"""Terminal UI for durable, per-user environment variables on Linux."""

from __future__ import annotations

import base64
import binascii
import argparse
import curses
import json
import os
import re
import sys
from importlib.metadata import PackageNotFoundError, version as distribution_version
import tempfile
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit, urlunsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from ._release_protocol import ReleaseProtocolError, update as update_release

APP_NAME = "envman"
MARKER_START = "# >>> envman environment >>>"
MARKER_END = "# <<< envman environment <<<"

def platform_environment_entry_limit() -> int:
    try:
        argument_limit = int(os.sysconf("SC_ARG_MAX"))
    except (AttributeError, OSError, ValueError):
        argument_limit = 8_192
    if sys.platform.startswith("linux"):
        try:
            per_string_limit = int(os.sysconf("SC_PAGE_SIZE")) * 32
        except (AttributeError, OSError, ValueError):
            per_string_limit = 131_072
        return max(1, min(argument_limit, per_string_limit) - 1)
    return max(1, argument_limit - 1)


MAX_ENVIRONMENT_ENTRY_BYTES = platform_environment_entry_limit()
MAX_VARIABLE_NAME_LENGTH = MAX_ENVIRONMENT_ENTRY_BYTES - 1
MAX_VALUE_LENGTH = MAX_ENVIRONMENT_ENTRY_BYTES - 2
MIN_TUI_WIDTH = 80
MIN_TUI_HEIGHT = 18
TITLE_ROW = 0
SUBTITLE_ROW = 1
HEADER_DIVIDER_ROW = 2
CATALOG_CONTROLS_ROW = 3
CATALOG_HINT_ROW = 4
LIST_DIVIDER_ROW = 5
LIST_FIRST_ROW = 6
DETAIL_MIN_ROWS = 2


def catalog_layout(height: int) -> tuple[int, int, int]:
    """Return the full catalog capacity between the fixed chrome rows."""
    return max(1, height - 14), LIST_FIRST_ROW, DETAIL_MIN_ROWS


def draw_catalog_controls(
    screen: curses.window,
    width: int,
    *,
    sort_label: str,
    filter_scope: str,
    filter_pattern: str,
    label_attribute: int,
    setting_attribute: int,
    pattern_attribute: int,
    key_attribute: int,
) -> None:
    """Draw consistently colored sort and filter controls without overflowing."""
    draw_colored_line(
        screen,
        CATALOG_CONTROLS_ROW,
        width,
        (
            ("Sort: ", label_attribute),
            (sort_label, setting_attribute),
            (" [", label_attribute),
            ("O", key_attribute),
            ("]  Filter: ", label_attribute),
            (filter_scope.title(), setting_attribute),
            (" [", label_attribute),
            ("M", key_attribute),
            ("]  Pattern: ", label_attribute),
            (repr(filter_pattern or "(all)"), pattern_attribute),
            (" [", label_attribute),
            ("F", key_attribute),
            ("]", label_attribute),
        ),
    )



def draw_colored_line(
    screen: curses.window,
    row: int,
    width: int,
    segments: tuple[tuple[str, int], ...],
) -> None:
    """Draw one clipped line while preserving colors for each text segment."""
    column = 2
    remaining = width - 4
    for text, attribute in segments:
        if remaining <= 0:
            return
        screen.addnstr(row, column, text, remaining, attribute)
        used = min(len(text), remaining)
        column += used
        remaining -= used
def draw_key_legend(
    screen: curses.window,
    row: int,
    width: int,
    entries: tuple[tuple[str, str], ...],
    *,
    key_attribute: int,
    label_attribute: int,
    separator: str = " ",
) -> None:
    """Draw a compact legend with all selector keys visually distinct."""
    column = 2
    remaining = width - 4
    for keys, label in entries:
        for text, attribute in ((keys, key_attribute), (f"{separator}{label}  ", label_attribute)):
            if remaining <= 0:
                return
            screen.addnstr(row, column, text, remaining, attribute)
            used = min(len(text), remaining)
            column += used
            remaining -= used


def draw_wrapped_segments(
    screen: curses.window,
    start_row: int,
    width: int,
    segments: tuple[tuple[str, int], ...],
    *,
    line_offset: int,
    max_lines: int,
) -> None:
    """Draw colored text segments across the selected-detail line boundaries."""
    available = max(1, width - 4)
    lines: list[list[tuple[str, int]]] = [[]]
    remaining = available
    for text, attribute in segments:
        while text:
            if remaining == 0:
                lines.append([])
                remaining = available
            consumed = min(len(text), remaining)
            lines[-1].append((text[:consumed], attribute))
            text = text[consumed:]
            remaining -= consumed
    for row, line in enumerate(lines[line_offset : line_offset + max_lines], start=start_row):
        column = 2
        for text, attribute in line:
            screen.addnstr(row, column, text, available, attribute)
            column += len(text)

SECRET_NAME_PATTERN = re.compile(
    r"(?:API[_-]?(?:KEY|SECRET)|SECRET|TOKEN|PASSWORD|PASS(?:WORD)?|"
    r"CREDENTIAL|PRIVATE[_-]?KEY|ENCRYPT(?:ION|ED)?|(?:^|_)KEY(?:_|$))",
    re.IGNORECASE,
)


def app_version() -> str:
    try:
        return distribution_version(APP_NAME)
    except PackageNotFoundError:
        try:
            return (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"

BACKUP_KEY_ENV = "ENVMAN_BACKUP_KEY"
ENCRYPTED_BACKUP_SCHEMA = "envman.encrypted-backup"
ENCRYPTED_BACKUP_SCHEMA_VERSION = 1
ENCRYPTED_BACKUP_SALT_BYTES = 16
ENCRYPTED_BACKUP_SCRYPT_N = 2**17
ENCRYPTED_BACKUP_SCRYPT_R = 8
ENCRYPTED_BACKUP_SCRYPT_P = 1
MAX_ENCRYPTED_BACKUP_BYTES = 8 * 1024 * 1024


def encrypted_backup_filename(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{APP_NAME}-{stamp}.json"


def encrypted_backup_destination(raw_destination: str | None, *, now: datetime | None = None) -> Path:
    if raw_destination is None or not raw_destination.strip():
        return Path.cwd() / encrypted_backup_filename(now)
    destination = Path(raw_destination).expanduser()
    if destination.exists() and destination.is_dir():
        return destination / encrypted_backup_filename(now)
    if raw_destination.endswith(os.sep):
        raise StoreError(f"Backup destination directory does not exist: {destination}")
    return destination


def backup_password() -> bytes:
    password = os.environ.get(BACKUP_KEY_ENV)
    if not password:
        raise StoreError(f"{BACKUP_KEY_ENV} is not set.")
    try:
        return password.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StoreError(f"{BACKUP_KEY_ENV} must be valid UTF-8 text.") from exc


def backup_fernet(salt: bytes) -> Fernet:
    try:
        key = Scrypt(
            salt=salt,
            length=32,
            n=ENCRYPTED_BACKUP_SCRYPT_N,
            r=ENCRYPTED_BACKUP_SCRYPT_R,
            p=ENCRYPTED_BACKUP_SCRYPT_P,
        ).derive(backup_password())
        return Fernet(base64.urlsafe_b64encode(key))
    except UnsupportedAlgorithm as exc:
        raise StoreError("This system cannot derive encrypted-backup keys with Scrypt.") from exc


def encrypted_backup_envelope(values: dict[str, str]) -> dict[str, Any]:
    salt = os.urandom(ENCRYPTED_BACKUP_SALT_BYTES)
    payload = {
        "variables": [
            {"name": name, "value": values[name]}
            for name in sorted(values)
        ],
    }
    plaintext = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    ciphertext = backup_fernet(salt).encrypt(plaintext).decode("ascii")
    return {
        "schema": ENCRYPTED_BACKUP_SCHEMA,
        "schema_version": ENCRYPTED_BACKUP_SCHEMA_VERSION,
        "envman_version": app_version(),
        "created_at": datetime.now(UTC).isoformat(),
        "encryption": {
            "algorithm": "fernet",
            "kdf": {
                "algorithm": "scrypt",
                "salt": base64.b64encode(salt).decode("ascii"),
                "length": 32,
                "n": ENCRYPTED_BACKUP_SCRYPT_N,
                "r": ENCRYPTED_BACKUP_SCRYPT_R,
                "p": ENCRYPTED_BACKUP_SCRYPT_P,
            },
        },
        "ciphertext": ciphertext,
    }


def write_encrypted_backup(destination: Path, values: dict[str, str]) -> dict[str, Any]:
    if destination.exists() and destination.is_dir():
        raise StoreError(f"Backup destination is a directory: {destination}")
    if destination.is_symlink():
        raise StoreError(f"Refusing to write encrypted backup through a symlink: {destination}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.parent.is_symlink():
            raise StoreError(f"Refusing to write encrypted backup through a symlinked directory: {destination.parent}")
        envelope = encrypted_backup_envelope(values)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(envelope, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                handle.write("\n")
            os.chmod(temporary_path, 0o600)
            temporary_path.replace(destination)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise StoreError(f"Cannot write encrypted backup {destination}: {exc}") from exc
    return envelope


def encrypted_backup_variables(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise StoreError(f"Refusing to read encrypted backup through a symlink: {path}")
    try:
        if not path.is_file():
            raise StoreError(f"Encrypted backup is not a file: {path}")
        if path.stat().st_size > MAX_ENCRYPTED_BACKUP_BYTES:
            raise StoreError(f"Encrypted backup exceeds the {MAX_ENCRYPTED_BACKUP_BYTES}-byte limit.")
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreError(f"Cannot read encrypted backup {path}: {exc}") from exc
    if not isinstance(envelope, dict):
        raise StoreError("Encrypted backup must contain a JSON object.")
    if envelope.get("schema") != ENCRYPTED_BACKUP_SCHEMA:
        raise StoreError("Unsupported encrypted-backup schema.")
    if type(envelope.get("schema_version")) is not int or envelope["schema_version"] != ENCRYPTED_BACKUP_SCHEMA_VERSION:
        raise StoreError("Unsupported encrypted-backup schema version.")
    encryption = envelope.get("encryption")
    if not isinstance(encryption, dict) or encryption.get("algorithm") != "fernet":
        raise StoreError("Unsupported encrypted-backup encryption algorithm.")
    kdf = encryption.get("kdf")
    expected_kdf = {
        "algorithm": "scrypt",
        "length": 32,
        "n": ENCRYPTED_BACKUP_SCRYPT_N,
        "r": ENCRYPTED_BACKUP_SCRYPT_R,
        "p": ENCRYPTED_BACKUP_SCRYPT_P,
    }
    if not isinstance(kdf, dict) or any(
        type(kdf.get(name)) is not type(value) or kdf.get(name) != value
        for name, value in expected_kdf.items()
    ):
        raise StoreError("Unsupported encrypted-backup key-derivation parameters.")
    salt_text = kdf.get("salt")
    ciphertext_text = envelope.get("ciphertext")
    if not isinstance(salt_text, str) or not isinstance(ciphertext_text, str):
        raise StoreError("Encrypted backup has invalid encryption metadata.")
    try:
        salt = base64.b64decode(salt_text, validate=True)
        ciphertext = ciphertext_text.encode("ascii")
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise StoreError("Encrypted backup has invalid encryption metadata.") from exc
    if len(salt) != ENCRYPTED_BACKUP_SALT_BYTES:
        raise StoreError("Encrypted backup has an invalid Scrypt salt.")
    try:
        payload = json.loads(backup_fernet(salt).decrypt(ciphertext).decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreError(f"Encrypted backup cannot be decrypted with {BACKUP_KEY_ENV}.") from exc
    if not isinstance(payload, dict) or set(payload) != {"variables"} or not isinstance(payload["variables"], list):
        raise StoreError("Encrypted backup contains an invalid variable payload.")
    values: dict[str, str] = {}
    for record in payload["variables"]:
        if not isinstance(record, dict) or set(record) != {"name", "value"}:
            raise StoreError("Encrypted backup contains an invalid variable record.")
        name = record["name"]
        value = record["value"]
        if not isinstance(name, str) or not isinstance(value, str):
            raise StoreError("Encrypted backup variable names and values must be text.")
        try:
            validate_assignment(name, value)
        except StoreError as exc:
            raise StoreError(f"Encrypted backup contains an invalid variable {name!r}: {exc}") from exc
        if name in values:
            raise StoreError(f"Encrypted backup contains duplicate variable {name}.")
        values[name] = value
    return values


SECRET_REFERENCE_SUFFIXES = ("_API_KEY_ENV",)
VISIBLE_SECRET_PLACEHOLDERS = frozenset({"change me"})


def normalize_name(value: str) -> str:
    return value.strip().replace("-", "_")


def normalize_value(value: str) -> str:
    return value.strip()


def validate_name(name: str) -> None:
    if not name.isascii() or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        raise StoreError("Names must use ASCII letters, digits, and underscores and cannot begin with a digit.")
    if len(name) > MAX_VARIABLE_NAME_LENGTH:
        raise StoreError(f"Names cannot exceed {MAX_VARIABLE_NAME_LENGTH} bytes on this system.")


def validate_value(value: str) -> None:
    try:
        byte_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise StoreError("Values must be valid UTF-8 text.") from exc
    if byte_length > MAX_VALUE_LENGTH:
        raise StoreError(f"Values cannot exceed {MAX_VALUE_LENGTH} bytes on this system.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise StoreError("Values cannot contain control characters.")


def validate_assignment(name: str, value: str) -> None:
    validate_name(name)
    validate_value(value)
    if is_secret_value(name, value) and len(value) < 6:
        raise StoreError("Secret values must be at least six characters long.")
    if len(name) + 1 + len(value.encode("utf-8")) > MAX_ENVIRONMENT_ENTRY_BYTES:
        raise StoreError(
            f"{name} and its value exceed this system's {MAX_ENVIRONMENT_ENTRY_BYTES}-byte environment-entry limit.",
        )


def is_secret_name(name: str) -> bool:
    normalized_name = name.upper()
    return (
        not normalized_name.endswith(SECRET_REFERENCE_SUFFIXES)
        and SECRET_NAME_PATTERN.search(name) is not None
    )


def is_secret_reference_name(name: str) -> bool:
    return name.upper().endswith(SECRET_REFERENCE_SUFFIXES)


def is_url_name(name: str) -> bool:
    return "URL" in name.upper()


def is_path_name(name: str) -> bool:
    return "PATH" in name.upper()


def secret_edge_length(value: str) -> int:
    """Return the number of visible characters at each edge of a secret."""
    if len(value) < 6:
        return 0
    if len(value) < 10:
        return 1
    if len(value) < 16:
        return 2
    return 4


def mask_value(value: str) -> str:
    if not value:
        return "(empty)"
    edge = secret_edge_length(value)
    if edge == 0:
        return "*" * len(value)
    return f"{value[:edge]}{'*' * (len(value) - (edge * 2))}{value[-edge:]}"


def is_secret_value(name: str, value: str) -> bool:
    if is_secret_name(name):
        return True
    if not is_url_name(name):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return True
    return parsed.password is not None




def sortable_value(name: str, value: str) -> str:
    if value in VISIBLE_SECRET_PLACEHOLDERS or not is_secret_value(name, value):
        return value
    edge = secret_edge_length(value)
    return f"{value[:edge]}{value[-edge:]}" if edge else ""


def display_value(name: str, value: str) -> str:
    if value in VISIBLE_SECRET_PLACEHOLDERS:
        return value
    return mask_value(value) if is_secret_value(name, value) else value


def truncate_for_display(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return f"{value[: width - 3]}..."


def validate_rename_sensitivity(old_name: str, new_name: str, value: str) -> None:
    validate_assignment(new_name, value)
    if is_secret_value(old_name, value) and not is_secret_value(new_name, value):
        raise StoreError(
            "Cannot rename a sensitive variable to a name that would expose its value.",
        )


def normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise StoreError("URL values must be syntactically valid.") from exc
    if not parsed.scheme:
        raise StoreError("URL values must include a scheme, such as https://.")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise StoreError("HTTP and HTTPS URL values must include a host.")
    return urlunsplit(parsed)


def normalize_path(value: str) -> tuple[str, tuple[str, ...]]:
    components = value.split(os.pathsep)
    if not components or any(not component for component in components):
        raise StoreError("PATH values cannot contain empty path entries.")
    normalized: list[str] = []
    missing: list[str] = []
    for component in components:
        candidate = Path(component).expanduser()
        if not candidate.is_absolute():
            raise StoreError("PATH values must use absolute paths.")
        resolved = candidate.resolve(strict=False)
        normalized.append(str(resolved))
        if not resolved.exists():
            missing.append(str(resolved))
    return os.pathsep.join(normalized), tuple(missing)


def prepare_value(name: str, raw_value: str) -> tuple[str, tuple[str, ...]]:
    value = normalize_value(raw_value)
    if is_secret_name(name) and not value:
        raise StoreError("Secret values cannot be empty.")
    if is_url_name(name):
        value, warnings = normalize_url(value), ()
    elif is_path_name(name):
        value, warnings = normalize_path(value)
    else:
        warnings = ()
    validate_assignment(name, value)
    return value, warnings


def prepare_import_value(name: str, value: str) -> tuple[str, tuple[str, ...]]:
    """Validate a process value without changing its bytes before persistence."""
    validate_assignment(name, value)
    if is_secret_name(name) and not value:
        raise StoreError("Secret values cannot be empty.")
    if is_url_name(name):
        normalize_url(value)
        return value, ()
    if not is_path_name(name):
        return value, ()
    components = value.split(os.pathsep)
    if not components or any(not component for component in components):
        raise StoreError("PATH values cannot contain empty path entries.")
    if any(not os.path.isabs(component) for component in components):
        raise StoreError("PATH values must use absolute paths.")
    return value, tuple(component for component in components if not Path(component).exists())


def credential_value_warning(name: str, value: str) -> str | None:
    if (
        value in VISIBLE_SECRET_PLACEHOLDERS
        or not is_secret_name(name)
        or is_url_name(name)
        or is_path_name(name)
    ):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.scheme and parsed.netloc:
        return f"{name} expects a credential, but the value looks like a URL."
    if os.path.isabs(value):
        return f"{name} expects a credential, but the value looks like an absolute path."
    return None


def append_credential_warning(
    name: str,
    value: str,
    warnings: tuple[str, ...],
) -> tuple[str, ...]:
    warning = credential_value_warning(name, value)
    return warnings if warning is None else (*warnings, warning)

def prepare_copied_value(
    target_name: str,
    source_name: str,
    values: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    source_value = values.get(source_name)
    if source_value is None:
        raise StoreError(f"{source_name} is not managed.")
    if not normalize_value(source_value):
        raise StoreError("Cannot copy an empty value.")
    source_is_sensitive = is_secret_value(source_name, source_value)
    if source_is_sensitive and not is_secret_value(target_name, source_value):
        raise StoreError("Cannot copy a sensitive value to a name that would expose it.")
    value, warnings = prepare_value(target_name, source_value)
    return value, () if source_is_sensitive else warnings

def normalized_reference_name(raw_value: str) -> str | None:
    candidate = normalize_name(raw_value)
    try:
        validate_name(candidate)
    except StoreError:
        return None
    return candidate.upper()


def referenced_value_name(raw_value: str, values: dict[str, str]) -> str | None:
    candidate = normalized_reference_name(raw_value)
    return candidate if candidate in values else None


def prepare_entered_value(
    target_name: str,
    raw_value: str,
    values: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    candidate = normalized_reference_name(raw_value)
    if is_secret_reference_name(target_name):
        if candidate is None:
            raise StoreError("Secret reference values must name a managed variable.")
        if candidate not in values:
            raise StoreError(f"{candidate} is not managed.")
        return candidate, ()
    if candidate is not None and candidate in values:
        return prepare_copied_value(target_name, candidate, values)
    return prepare_value(target_name, raw_value)


@dataclass
class EnvironmentImportCandidate:
    source_name: str
    name: str | None
    value: str | None
    warnings: tuple[str, ...]
    error: str | None
    state: str = "invalid"

    @property
    def selectable(self) -> bool:
        return self.error is None and self.name is not None and self.value is not None


def environment_import_candidates(
    environment: dict[str, str],
    managed_values: dict[str, str],
) -> list[EnvironmentImportCandidate]:
    candidates: list[EnvironmentImportCandidate] = []
    for source_name, raw_value in environment.items():
        try:
            name = source_name
            validate_name(name)
            value, path_warnings = prepare_import_value(name, raw_value)
            warnings = () if is_secret_value(name, value) else path_warnings
            warnings = append_credential_warning(name, value, warnings)
        except StoreError as exc:
            candidates.append(
                EnvironmentImportCandidate(source_name, None, None, (), str(exc)),
            )
            continue
        candidates.append(EnvironmentImportCandidate(source_name, name, value, warnings, None))

    normalized_names: dict[str, int] = {}
    for candidate in candidates:
        if candidate.name is not None:
            normalized_names[candidate.name] = normalized_names.get(candidate.name, 0) + 1
    for candidate in candidates:
        if candidate.name is not None and normalized_names[candidate.name] > 1:
            candidate.error = "Multiple environment names normalize to the same managed name."
    available_names = {
        candidate.name
        for candidate in candidates
        if candidate.name is not None and candidate.error is None
    } | set(managed_values)
    for candidate in candidates:
        if not candidate.selectable:
            continue
        assert candidate.name is not None and candidate.value is not None
        if is_secret_reference_name(candidate.name):
            try:
                validate_name(candidate.value)
            except StoreError:
                candidate.error = "Credential reference must name an importable or managed variable."
                continue
            if candidate.value not in available_names:
                candidate.error = "Credential reference does not name an importable or managed variable."
                continue
        if candidate.name not in managed_values:
            candidate.state = "add"
        elif managed_values[candidate.name] == candidate.value:
            candidate.state = "unchanged"
        else:
            candidate.state = "collision"
    return candidates


def prepare_environment_import(
    candidates: list[EnvironmentImportCandidate],
    selected_sources: set[str],
    managed_values: dict[str, str],
    *,
    allow_replace: bool,
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    selected = [candidate for candidate in candidates if candidate.source_name in selected_sources]
    if not selected:
        raise StoreError("Select at least one environment variable to import.")
    invalid = next((candidate for candidate in selected if not candidate.selectable), None)
    if invalid is not None:
        raise StoreError(f"{invalid.source_name} cannot be imported: {invalid.error}")
    collisions = tuple(
        candidate.name
        for candidate in selected
        if candidate.state == "collision" and candidate.name is not None
    )
    if collisions and not allow_replace:
        raise StoreError(
            "Import would replace managed variable(s): "
            + ", ".join(sorted(collisions))
            + ". Re-run with --replace or deselect them.",
        )
    imported = {candidate.name: candidate.value for candidate in selected if candidate.name is not None and candidate.value is not None}
    combined = {**managed_values, **imported}
    for name, value in imported.items():
        if not is_secret_reference_name(name):
            continue
        try:
            validate_name(value)
        except StoreError as exc:
            raise StoreError(f"{name} must reference a managed variable selected for import.") from exc
        if value not in combined:
            raise StoreError(f"{name} must reference a managed variable selected for import.")
    warnings = tuple(
        warning
        for candidate in selected
        for warning in candidate.warnings
    )
    return imported, warnings, collisions

def configuration_home(home: Path) -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    if not configured:
        return home / ".config"
    path = Path(configured)
    if not path.is_absolute():
        raise StoreError("XDG_CONFIG_HOME must be an absolute path.")
    return path



class StoreError(Exception):
    """A durable environment file could not be managed safely."""


@dataclass
class EnvironmentStore:
    home: Path
    config_home: Path

    def __post_init__(self) -> None:
        self.utility_dir = self.config_home / "envman"
        self.target = self.utility_dir / "environment.conf"
        self.backup_dir = self.utility_dir / "backups"
        self.loader = self.utility_dir / "load-env.sh"
        self.fish_loader = self.config_home / "fish" / "conf.d" / "envman.fish"
        self.lines: list[str] = []
        self.values: dict[str, str] = {}
        self.original_keys: set[str] = set()

    @staticmethod
    def validate_name(name: str) -> None:
        validate_name(name)

    @staticmethod
    def validate_value(value: str) -> None:
        validate_value(value)

    def load(self) -> None:
        self.lines = []
        self.values = {}
        self.original_keys = set()
        if not self.target.exists():
            return
        if self.target.is_symlink():
            raise StoreError(f"Refusing to manage symlinked environment file: {self.target}")
        try:
            content = self.target.read_text(encoding="utf-8")
        except OSError as exc:
            raise StoreError(f"Cannot read {self.target}: {exc}") from exc

        self.lines = content.splitlines()
        for line in self.lines:
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise StoreError(f"Unsupported line in {self.target}: {line!r}")
            name, value = line.split("=", 1)
            validate_assignment(name, value)
            if name in self.values:
                raise StoreError(f"Duplicate variable in {self.target}: {name}")
            self.values[name] = value
            self.original_keys.add(name)

    def backup(self, path: Path) -> None:
        if not path.exists():
            return
        if path.is_symlink():
            raise StoreError(f"Refusing to back up symlinked path: {path}")
        self.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.backup_dir, 0o700)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive = self.backup_dir / f"{path.name}.{stamp}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(path, arcname=path.name, recursive=False)
        os.chmod(archive, 0o600)

    def write_values(self) -> None:
        if self.target.is_symlink():
            raise StoreError(f"Refusing to replace symlinked environment file: {self.target}")
        self.target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backup(self.target)
        seen: set[str] = set()
        rendered: list[str] = []
        for line in self.lines:
            if not line or line.startswith("#"):
                rendered.append(line)
                continue
            name = line.split("=", 1)[0]
            if name not in self.values:
                continue
            rendered.append(f"{name}={self.values[name]}")
            seen.add(name)
        for name in sorted(self.values):
            if name not in seen:
                rendered.append(f"{name}={self.values[name]}")
        temporary = self.target.with_name(f".{self.target.name}.tmp")
        try:
            temporary.write_text("\n".join(rendered) + ("\n" if rendered else ""), encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise StoreError(f"Cannot write {self.target}: {exc}") from exc
        self.lines = rendered

    def _install_posix_loader(self) -> None:
        self.utility_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.utility_dir.is_symlink() or self.loader.is_symlink():
            raise StoreError("Refusing to write through a symlink in envman configuration.")
        source = f'''#!/bin/sh
# Managed by {APP_NAME}; this file remains usable if the application is removed.
_envman_config_home="${{XDG_CONFIG_HOME:-$HOME/.config}}"
case "$_envman_config_home" in /*) ;; *) _envman_config_home="$HOME/.config" ;; esac
_envman_environment_file="$_envman_config_home/envman/environment.conf"
if [ -r "$_envman_environment_file" ]; then
  while IFS= read -r _envman_environment_line || [ -n "$_envman_environment_line" ]; do
    case "$_envman_environment_line" in
      ''|\\#*) continue ;;
    esac
    export "$_envman_environment_line" || printf '%s\n' "envman: skipped invalid environment assignment" >&2
  done < "$_envman_environment_file"
fi
unset _envman_config_home _envman_environment_file _envman_environment_line
'''
        self.loader.write_text(source, encoding="utf-8")
        os.chmod(self.loader, 0o600)

    def _append_profile_loader(self, profile: Path) -> None:
        if profile.is_symlink():
            raise StoreError(f"Refusing to update symlinked shell profile: {profile}")
        if profile.exists() and MARKER_START in profile.read_text(encoding="utf-8"):
            return
        self.backup(profile)
        profile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with profile.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{MARKER_START}\n")
            handle.write('_envman_config_home="${XDG_CONFIG_HOME:-$HOME/.config}"\n')
            handle.write('case "$_envman_config_home" in /*) ;; *) _envman_config_home="$HOME/.config" ;; esac\n')
            handle.write('[ -r "$_envman_config_home/envman/load-env.sh" ] && . "$_envman_config_home/envman/load-env.sh"\n')
            handle.write('unset _envman_config_home\n')
            handle.write(f"{MARKER_END}\n")

    def _install_fish_loader(self) -> None:
        if self.fish_loader.is_symlink():
            raise StoreError(f"Refusing to update symlinked fish loader: {self.fish_loader}")
        self.fish_loader.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = '''# Managed by envman; remains usable if the application is removed.
set -l envman_config_home "$HOME/.config"
if set -q XDG_CONFIG_HOME; and string match -qr '^/' -- "$XDG_CONFIG_HOME"
    set envman_config_home "$XDG_CONFIG_HOME"
end
set -l envman_environment_file "$envman_config_home/envman/environment.conf"
if test -r "$envman_environment_file"
    while read -l envman_environment_line
        if test -z "$envman_environment_line"; or string match -qr '^#' -- "$envman_environment_line"
            continue
        end
        set -l envman_environment_parts (string split -m1 '=' -- "$envman_environment_line")
        if test (count $envman_environment_parts) -eq 2
            set -gx $envman_environment_parts[1] $envman_environment_parts[2]
        end
    end < "$envman_environment_file"
end
'''
        self.fish_loader.write_text(source, encoding="utf-8")
        os.chmod(self.fish_loader, 0o600)

    def install_loaders(self) -> None:
        try:
            self._install_posix_loader()
            self._append_profile_loader(self.home / ".profile")
            for bash_login_file in (".bash_profile", ".bash_login"):
                candidate = self.home / bash_login_file
                if candidate.exists():
                    self._append_profile_loader(candidate)
                    break
            for profile_name in (".bashrc", ".zprofile", ".zshrc"):
                self._append_profile_loader(self.home / profile_name)
            self._install_fish_loader()
        except OSError as exc:
            raise StoreError(f"Cannot install envman shell loaders: {exc}") from exc

    def save(self) -> None:
        self.validate_child_environment()
        self.install_loaders()
        self.write_values()

    def child_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        for name in self.original_keys:
            environment.pop(name, None)
        environment.update(self.values)
        return environment

    def validate_child_environment(self) -> None:
        try:
            argument_limit = int(os.sysconf("SC_ARG_MAX"))
        except (AttributeError, OSError, ValueError):
            return
        environment = self.child_environment()
        try:
            payload_bytes = sum(
                len(name.encode("utf-8")) + 1 + len(value.encode("utf-8")) + 1
                for name, value in environment.items()
            )
        except UnicodeEncodeError as exc:
            raise StoreError("The inherited environment contains text that cannot be encoded as UTF-8.") from exc
        pointer_bytes = (len(environment) + 3) * (8 if sys.maxsize > 2**32 else 4)
        reserved_bytes = 8_192
        if payload_bytes + pointer_bytes + reserved_bytes > argument_limit:
            raise StoreError(
                "Managed values would exceed the operating system's combined argument and environment budget.",
            )


class EnvmanTUI:
    def __init__(self, screen: curses.window, store: EnvironmentStore, *, colors_enabled: bool = True) -> None:
        self.screen = screen
        self.store = store
        self.colors_enabled = colors_enabled
        self.selected = 0
        self.selected_names: set[str] = set()
        self.scroll_offset = 0
        self.sort_mode = "name_asc"
        self.filter_scope = "both"
        self.filter_pattern = ""
        self.status = "Ready. Space selects; A creates a variable."
        self.status_attribute = curses.A_REVERSE | curses.A_BOLD if colors_enabled else curses.A_NORMAL
        self.name_attribute = curses.A_BOLD
        self.value_attribute = curses.A_NORMAL
        self.number_attribute = curses.A_NORMAL
        self.title_attribute = curses.A_BOLD
        self.control_label_attribute = curses.A_BOLD
        self.setting_attribute = curses.A_BOLD
        self.pattern_attribute = curses.A_NORMAL
        self.selected_attribute = curses.A_REVERSE if colors_enabled else curses.A_BOLD
        self.detail_offset = 0
        self.start_shell = True

    def configure_colors(self) -> None:
        try:
            if not self.colors_enabled or not curses.has_colors():
                return
            curses.start_color()
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_YELLOW)
            self.status_attribute = curses.color_pair(1) | curses.A_BOLD
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            curses.init_pair(2, curses.COLOR_GREEN, background)
            curses.init_pair(3, curses.COLOR_YELLOW, background)
            curses.init_pair(4, curses.COLOR_BLUE, background)
            curses.init_pair(5, curses.COLOR_MAGENTA, background)
            curses.init_pair(
                7,
                208 if getattr(curses, "COLORS", 0) >= 256 else curses.COLOR_YELLOW,
                background,
            )
            self.name_attribute = curses.color_pair(2) | curses.A_BOLD
            self.value_attribute = curses.color_pair(3)
            self.number_attribute = curses.color_pair(4)
            self.title_attribute = curses.color_pair(5) | curses.A_BOLD
            self.control_label_attribute = curses.color_pair(7) | curses.A_BOLD
            self.setting_attribute = self.name_attribute
            self.pattern_attribute = self.value_attribute
        except curses.error:
            pass
    def catalog_names(self) -> list[str]:
        pattern = self.filter_pattern.casefold()
        names = [
            name
            for name, value in self.store.values.items()
            if not pattern
            or (
                self.filter_scope in {"name", "both"} and pattern in name.casefold()
            )
            or (
                self.filter_scope in {"value", "both"}
                and pattern in sortable_value(name, value).casefold()
            )
        ]
        if self.sort_mode == "name_asc":
            names = sorted(names)
        elif self.sort_mode == "name_desc":
            names = sorted(names, reverse=True)
        else:
            names = sorted(
                names,
                key=lambda name: (sortable_value(name, self.store.values[name]).casefold(), name),
                reverse=self.sort_mode == "value_desc",
            )
        self.selected_names.intersection_update(names)
        return names

    def catalog_row_limit(self, height: int) -> int:
        return catalog_layout(height)[0]

    def _clamp_catalog_selection(self, names: list[str]) -> None:
        self.selected = min(max(0, self.selected), max(0, len(names) - 1))

    def _ensure_visible(self, names: list[str], visible_rows: int) -> None:
        self._clamp_catalog_selection(names)
        maximum_offset = max(0, len(names) - visible_rows)
        self.scroll_offset = min(max(0, self.scroll_offset), maximum_offset)
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + visible_rows:
            self.scroll_offset = self.selected - visible_rows + 1

    def detail_lines(self, width: int) -> list[str]:
        name = self.current_name()
        if name is None:
            return ["Selected: (none)"]
        value = self.store.values[name]
        text = f"Selected: {name} = {display_value(name, value)}"
        available = max(1, width - 4)
        return [text[index : index + available] for index in range(0, len(text), available)] or [""]

    def draw_detail(
        self,
        width: int,
        first_row: int,
        visible_rows: int,
        detail_rows: int,
        horizontal_line: int,
    ) -> None:
        divider_row = first_row + visible_rows
        detail_start = divider_row + 1
        self.screen.hline(divider_row, 2, horizontal_line, width - 4)
        lines = self.detail_lines(width)
        self.detail_offset = min(self.detail_offset, max(0, len(lines) - detail_rows))
        name = self.current_name()
        if name is None:
            self.screen.addnstr(detail_start, 2, lines[self.detail_offset], width - 4, curses.A_DIM)
            return
        draw_wrapped_segments(
            self.screen,
            detail_start,
            width,
            (
                ("Selected: ", curses.A_DIM),
                (name, self.name_attribute),
                (" = ", curses.A_DIM),
                (display_value(name, self.store.values[name]), self.value_attribute),
            ),
            line_offset=self.detail_offset,
            max_lines=detail_rows,
        )

    def scroll_detail(self, distance: int) -> None:
        lines = self.detail_lines(self.screen.getmaxyx()[1])
        self.detail_offset = min(max(0, self.detail_offset + distance), max(0, len(lines) - DETAIL_MIN_ROWS))

    def _draw_size_error(self, height: int, width: int) -> None:
        self.screen.erase()
        lines = (
            "Terminal size too small:",
            f" Width = {width} Height = {height}",
            "Needed for current config:",
            f"Width = {MIN_TUI_WIDTH} Height = {MIN_TUI_HEIGHT}",
        )
        for index, text in enumerate(lines):
            row = min(
                max(0, (height // 2) - 2 + index + (1 if index > 1 else 0)),
                max(0, height - 1),
            )
            column = max(0, (width - len(text)) // 2)
            available = max(0, width - column - (1 if row == height - 1 else 0))
            if available:
                self.screen.addnstr(row, column, text, available)
        self.screen.refresh()
    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < MIN_TUI_HEIGHT or width < MIN_TUI_WIDTH:
            self._draw_size_error(height, width)
            return

        self.screen.addnstr(TITLE_ROW, 2, "Envman · Environment Variable Manager", width - 4, self.title_attribute)
        self.screen.addnstr(SUBTITLE_ROW, 2, str(self.store.target), width - 4, curses.A_DIM)
        horizontal_line = getattr(curses, "ACS_HLINE", ord("-"))
        self.screen.hline(HEADER_DIVIDER_ROW, 2, horizontal_line, width - 4)
        sort_label = {
            "name_asc": "Name ↑",
            "name_desc": "Name ↓",
            "value_asc": "Value ↑",
            "value_desc": "Value ↓",
        }[self.sort_mode]
        draw_catalog_controls(
            self.screen,
            width,
            sort_label=sort_label,
            filter_scope=self.filter_scope,
            filter_pattern=self.filter_pattern,
            label_attribute=self.control_label_attribute,
            setting_attribute=self.setting_attribute,
            pattern_attribute=self.pattern_attribute,
            key_attribute=self.number_attribute | curses.A_BOLD,
        )
        names = self.catalog_names()
        visible_rows, first_row, detail_rows = catalog_layout(height)
        self._ensure_visible(names, visible_rows)
        draw_colored_line(
            self.screen,
            CATALOG_HINT_ROW,
            width,
            (
                (f"{len(names)} shown · ", curses.A_DIM),
                ("Space", self.number_attribute | curses.A_BOLD),
                (" toggles · ", curses.A_DIM),
                ("Up/Down", self.number_attribute | curses.A_BOLD),
                (" moves", curses.A_DIM),
            ),
        )
        self.screen.hline(LIST_DIVIDER_ROW, 2, horizontal_line, width - 4)
        if names:
            for index, name in enumerate(
                names[self.scroll_offset : self.scroll_offset + visible_rows],
                start=self.scroll_offset,
            ):
                row = first_row + index - self.scroll_offset
                focused = index == self.selected
                row_attribute = self.selected_attribute if focused else curses.A_NORMAL
                marker = "[*]" if name in self.selected_names else "[ ]"
                preview = display_value(name, self.store.values[name])
                text_capacity = max(1, width - 10)
                name_text = truncate_for_display(name, max(3, text_capacity // 2))
                value_text = truncate_for_display(preview, max(0, text_capacity - len(name_text) - 3))
                column = 4
                remaining = width - 8
                for text, attribute in (
                    (marker, self.number_attribute | row_attribute),
                    (" ", row_attribute),
                    (name_text, self.name_attribute | row_attribute),
                    (" = ", curses.A_DIM | row_attribute),
                    (value_text, self.value_attribute | row_attribute),
                ):
                    if remaining <= 0:
                        break
                    self.screen.addnstr(row, column, text, remaining, attribute)
                    used = min(len(text), remaining)
                    column += used
                    remaining -= used
        else:
            message = (
                "No variables match the filter. Press F to change or clear it."
                if self.store.values
                else "No variables yet. Press A to create one."
            )
            self.screen.addnstr(first_row, 4, message, width - 8, curses.A_DIM)
        self.draw_detail(width, first_row, visible_rows, detail_rows, horizontal_line)
        self.screen.hline(height - 5, 2, horizontal_line, width - 4)
        draw_key_legend(
            self.screen,
            height - 4,
            width,
            (
                ("A", "dd"),
                ("E", "dit"),
                ("C", "opy"),
                ("R", "ename"),
                ("D", "elete"),
            ),
            key_attribute=self.number_attribute | curses.A_BOLD,
            label_attribute=curses.A_DIM,
            separator="",
        )
        draw_key_legend(
            self.screen,
            height - 3,
            width,
            (
                ("B", "ackup"),
                ("I", "mport"),
                ("J", "SON import"),
                ("O", "rder"),
                ("F", "ilter"),
                ("M", "ode"),
                ("[/]", "view"),
                ("Esc/Q", "reload"),
            ),
            key_attribute=self.number_attribute | curses.A_BOLD,
            label_attribute=curses.A_DIM,
            separator="",
        )
        status_width = width - 4
        self.screen.addnstr(
            height - 2,
            2,
            f" {self.status} ".ljust(status_width),
            status_width,
            self.status_attribute,
        )
        self.screen.refresh()


    def _set_cursor_visibility(self, visible: bool) -> None:
        try:
            curses.curs_set(1 if visible else 0)
        except curses.error:
            pass

    def prompt(self, label: str, *, secret: bool = False, variable_name: bool = False) -> str | None:
        value: list[str] = []
        self._set_cursor_visibility(True)
        was_undersized = False
        try:
            while True:
                height, width = self.screen.getmaxyx()
                if height < MIN_TUI_HEIGHT or width < MIN_TUI_WIDTH:
                    self._set_cursor_visibility(False)
                    self._draw_size_error(height, width)
                    was_undersized = True
                    if self.screen.get_wch() in ("\x1b", 27):
                        return None
                    continue
                if was_undersized:
                    self.draw()
                    self._set_cursor_visibility(True)
                    was_undersized = False
                shown = "*" * len(value) if secret else "".join(value)
                available = max(1, width - 4)
                label_prefix = truncate_for_display(f"{label} (Esc cancels): ", max(12, available // 2))
                input_width = max(1, available - len(label_prefix))
                visible_value = truncate_for_display(shown, input_width)
                if len(shown) > input_width:
                    tail_width = max(0, input_width - 3)
                    visible_value = f"...{shown[-tail_width:] if tail_width else ''}"
                prompt_row = height - 2
                self.screen.move(prompt_row, 0)
                self.screen.clrtoeol()
                self.screen.addnstr(prompt_row, 2, f"{label_prefix}{visible_value}", available)
                self.screen.move(prompt_row, min(width - 1, 2 + len(label_prefix) + len(visible_value)))
                self.screen.refresh()
                key = self.screen.get_wch()
                if key in ("\n", "\r", curses.KEY_ENTER):
                    return "".join(value)
                if key in ("\x1b", 27):
                    return None
                if key in ("\x08", "\x7f", curses.KEY_BACKSPACE):
                    if value:
                        value.pop()
                    continue
                if not isinstance(key, str) or not key.isprintable():
                    continue
                if variable_name:
                    if not key.isascii():
                        continue
                    key = "_" if key == "-" else key.upper()
                    if not (key.isalpha() or key.isdigit() or key == "_"):
                        continue
                    if not value and key.isdigit():
                        continue
                value.append(key)
        finally:
            self._set_cursor_visibility(False)

    def prompt_name(self, label: str) -> str | None:
        return self.prompt(label, variable_name=True)
    def confirm(self, question: str) -> bool:
        answer = self.prompt(f"{question} [y/N]")
        return answer is not None and answer.strip().lower() in {"y", "yes"}

    def _select_catalog_name(self, name: str | None) -> None:
        names = self.catalog_names()
        if name is not None and name in names:
            self.selected = names.index(name)
        else:
            self._clamp_catalog_selection(names)
        self.scroll_offset = 0
        self.detail_offset = 0

    def current_name(self) -> str | None:
        names = self.catalog_names()
        self._clamp_catalog_selection(names)
        return names[self.selected] if names else None

    def toggle_current(self) -> None:
        name = self.current_name()
        if name is None:
            self.status = "No variables match the current filter."
            return
        if name in self.selected_names:
            self.selected_names.remove(name)
            self.status = f"{name} removed from the selection."
        else:
            self.selected_names.add(name)
            self.status = f"{name} selected."

    def cycle_sort(self) -> None:
        current_name = self.current_name()
        modes = ("name_asc", "name_desc", "value_asc", "value_desc")
        self.sort_mode = modes[(modes.index(self.sort_mode) + 1) % len(modes)]
        self._select_catalog_name(current_name)
        self.status = f"Sort: {self.sort_mode.replace('_', ' ')}."

    def cycle_filter_scope(self) -> None:
        current_name = self.current_name()
        scopes = ("both", "name", "value")
        self.filter_scope = scopes[(scopes.index(self.filter_scope) + 1) % len(scopes)]
        self._select_catalog_name(current_name)
        self.status = f"Filter scope: {self.filter_scope}."

    def set_filter(self) -> None:
        current_name = self.current_name()
        raw_pattern = self.prompt("Filter pattern (empty clears)")
        if raw_pattern is None:
            self.status = "Filter unchanged."
            return
        self.filter_pattern = normalize_value(raw_pattern)
        self._select_catalog_name(current_name)
        self.status = "Filter cleared." if not self.filter_pattern else "Filter updated."

    def move_selection(self, distance: int) -> None:
        names = self.catalog_names()
        self._clamp_catalog_selection(names)
        if names:
            self.selected = min(max(0, self.selected + distance), len(names) - 1)



    def persist_change(
        self,
        previous_values: dict[str, str],
        previous_selection: int,
        message: str,
        warnings: tuple[str, ...] = (),
        previous_selected_names: set[str] | None = None,
    ) -> None:
        try:
            self.store.save()
        except StoreError as exc:
            self.store.values = previous_values
            self.selected = previous_selection
            if previous_selected_names is not None:
                self.selected_names = previous_selected_names
            self.status = f"Change was not saved: {exc}"
            return
        warning = f" Warning: {len(warnings)} configured path(s) do not exist yet." if warnings else ""
        self.status = f"{message} Saved.{warning}"

    def prompt_prepared_value(
        self,
        name: str,
        label: str,
        *,
        secret: bool,
    ) -> tuple[str, str, tuple[str, ...]] | None:
        while True:
            raw_value = self.prompt(label, secret=secret)
            if raw_value is None:
                return None
            value, warnings = prepare_entered_value(name, raw_value, self.store.values)
            warning = credential_value_warning(name, value)
            if warning is not None and self.prompt(f"{warning} Enter saves; Esc re-enters") is None:
                continue
            return raw_value, value, warnings

    def add(self) -> None:
        raw_name = self.prompt_name("New variable name")
        if raw_name is None:
            self.status = "Create cancelled."
            return
        name = normalize_name(raw_name)
        try:
            validate_name(name)
        except StoreError as exc:
            self.status = str(exc)
            return
        if name in self.store.values:
            self.status = f"{name} already exists; use edit instead."
            return
        try:
            entered = self.prompt_prepared_value(name, f"Value for {name}", secret=is_secret_name(name))
        except StoreError as exc:
            self.status = str(exc)
            return
        if entered is None:
            self.status = "Create cancelled."
            return
        raw_value, value, warnings = entered
        previous_values = self.store.values.copy()
        previous_selection = self.selected
        self.store.values[name] = value
        self._select_catalog_name(name)
        trimmed = raw_name != name or raw_value != value
        self.persist_change(previous_values, previous_selection, f"{name} added" + ("; surrounding whitespace removed." if trimmed else "."), warnings)

    def edit(self) -> None:
        name = self.current_name()
        if name is None:
            self.status = "Nothing to edit."
            return
        try:
            entered = self.prompt_prepared_value(
                name,
                f"Replacement value for {name}",
                secret=is_secret_value(name, self.store.values[name]),
            )
        except StoreError as exc:
            self.status = str(exc)
            return
        if entered is None:
            self.status = "Edit cancelled."
            return
        raw_value, value, warnings = entered
        previous_values = self.store.values.copy()
        previous_selection = self.selected
        self.store.values[name] = value
        self.persist_change(previous_values, previous_selection, f"{name} updated" + ("; surrounding whitespace removed." if raw_value != value else "."), warnings)

    def _selected_group_names(self) -> list[str]:
        names = self.catalog_names()
        selected = [name for name in names if name in self.selected_names]
        if selected:
            return selected
        current = self.current_name()
        return [current] if current is not None else []

    def copy_value(self) -> None:
        targets = self._selected_group_names()
        if not targets:
            self.status = "Nothing to copy into."
            return
        while True:
            raw_source_name = self.prompt_name(f"Copy value to {len(targets)} variable(s) from")
            if raw_source_name is None:
                self.status = "Copy cancelled."
                return
            source_name = normalize_name(raw_source_name)
            try:
                validate_name(source_name)
                prepared: dict[str, str] = {}
                warnings: tuple[str, ...] = ()
                credential_warnings: list[str] = []
                for target in targets:
                    value, target_warnings = prepare_copied_value(target, source_name, self.store.values)
                    prepared[target] = value
                    warnings += target_warnings
                    warning = credential_value_warning(target, value)
                    if warning is not None:
                        credential_warnings.append(warning)
            except StoreError as exc:
                self.status = str(exc)
                return
            if credential_warnings:
                warning_text = (
                    credential_warnings[0]
                    if len(credential_warnings) == 1
                    else f"{len(credential_warnings)} targets have credential warnings."
                )
                if self.prompt(f"{warning_text} Enter saves; Esc re-enters") is None:
                    continue
            break
        previous_values = self.store.values.copy()
        previous_selection = self.selected
        previous_selected_names = self.selected_names.copy()
        self.store.values.update(prepared)
        self.persist_change(
            previous_values,
            previous_selection,
            f"{source_name} copied to {len(targets)} variable(s).",
            warnings,
            previous_selected_names,
        )

    def rename(self) -> None:
        old_name = self.current_name()
        if old_name is None:
            self.status = "Nothing to rename."
            return
        raw_name = self.prompt_name(f"Rename {old_name} to")
        if raw_name is None:
            self.status = "Rename cancelled."
            return
        new_name = normalize_name(raw_name)
        try:
            validate_name(new_name)
        except StoreError as exc:
            self.status = str(exc)
            return
        if new_name in self.store.values:
            self.status = f"{new_name} already exists."
            return
        try:
            validate_rename_sensitivity(old_name, new_name, self.store.values[old_name])
        except StoreError as exc:
            self.status = str(exc)
            return
        previous_values = self.store.values.copy()
        previous_selection = self.selected
        previous_selected_names = self.selected_names.copy()
        self.store.values[new_name] = self.store.values.pop(old_name)
        if old_name in self.selected_names:
            self.selected_names.remove(old_name)
            self.selected_names.add(new_name)
        self._select_catalog_name(new_name)
        self.persist_change(
            previous_values,
            previous_selection,
            f"{old_name} renamed to {new_name}" + ("; surrounding whitespace removed." if raw_name != new_name else "."),
            previous_selected_names=previous_selected_names,
        )

    def delete(self) -> None:
        targets = self._selected_group_names()
        if not targets:
            self.status = "Nothing to delete."
            return
        label = f"{len(targets)} variable(s)" if len(targets) > 1 else targets[0]
        if not self.confirm(f"Delete {label}?"):
            self.status = "Delete cancelled."
            return
        previous_values = self.store.values.copy()
        previous_selection = self.selected
        previous_selected_names = self.selected_names.copy()
        for name in targets:
            self.store.values.pop(name, None)
        names = self.catalog_names()
        self._ensure_visible(names, self.catalog_row_limit(self.screen.getmaxyx()[0]))
        self._clamp_catalog_selection(self.catalog_names())
        self.persist_change(
            previous_values,
            previous_selection,
            f"Deleted {len(targets)} variable(s).",
            previous_selected_names=previous_selected_names,
        )
    def backup_group(self) -> None:
        self.catalog_names()
        self.export_encrypted_backup()

    def import_environment(self) -> None:
        preview = EnvironmentImportTUI(self.screen, self.store, colors_enabled=self.colors_enabled)
        preview.run()
        if preview.applied:
            self._select_catalog_name(preview.last_name)
        self.status = preview.status
    def export_encrypted_backup(self) -> None:
        ordered_names = self.catalog_names()
        selected = set(self.selected_names)
        values = (
            {
                name: self.store.values[name]
                for name in ordered_names
                if name in selected and name in self.store.values
            }
            if selected
            else self.store.values
        )
        raw_destination = self.prompt("Encrypted backup destination (empty uses envman timestamp)")
        if raw_destination is None:
            self.status = "Encrypted backup export cancelled."
            return
        try:
            destination = encrypted_backup_destination(raw_destination)
            write_encrypted_backup(destination, values)
        except StoreError as exc:
            self.status = str(exc)
            return
        scope = "selected " if selected else ""
        self.status = f"Encrypted backup of {len(values)} {scope}variable(s) saved to {destination}."

    def import_encrypted_backup(self) -> None:
        raw_source = self.prompt("Encrypted backup path")
        if raw_source is None or not raw_source.strip():
            self.status = "Encrypted backup import cancelled."
            return
        try:
            environment = encrypted_backup_variables(Path(raw_source).expanduser())
        except StoreError as exc:
            self.status = str(exc)
            return
        preview = EnvironmentImportTUI(
            self.screen,
            self.store,
            environment,
            source_label="encrypted backup",
            colors_enabled=self.colors_enabled,
        )
        preview.status = "Encrypted backup loaded. Select variables to import; Esc returns without changes."
        preview.run()
        if preview.applied:
            self._select_catalog_name(preview.last_name)
        self.status = preview.status


    def run(self) -> bool:
        self._set_cursor_visibility(False)
        self.configure_colors()
        self.screen.keypad(True)
        while True:
            self.draw()
            key = self.screen.get_wch()
            if key in ("q", "Q", "\x1b", 27):
                return False
            height, width = self.screen.getmaxyx()
            if height < MIN_TUI_HEIGHT or width < MIN_TUI_WIDTH:
                continue
            if key in ("a", "A"):
                self.add()
            elif key in ("e", "E", "\n", "\r", curses.KEY_ENTER):
                self.edit()
            elif key == " ":
                self.toggle_current()
            elif key in ("c", "C"):
                self.copy_value()
            elif key in ("r", "R"):
                self.rename()
            elif key in ("d", "D"):
                self.delete()
            elif key in ("o", "O"):
                self.cycle_sort()
            elif key in ("f", "F"):
                self.set_filter()
            elif key in ("i", "I"):
                self.import_environment()
            elif key in ("j", "J"):
                self.import_encrypted_backup()
            elif key in ("b", "B"):
                self.backup_group()
            elif key in ("m", "M"):
                self.cycle_filter_scope()
            elif key == curses.KEY_UP:
                self.move_selection(-1)
                self.detail_offset = 0
            elif key == curses.KEY_DOWN:
                self.move_selection(1)
                self.detail_offset = 0
            elif key == "[":
                self.scroll_detail(-1)
            elif key == "]":
                self.scroll_detail(1)


class EnvironmentImportTUI:
    def __init__(
        self,
        screen: curses.window,
        store: EnvironmentStore,
        environment: dict[str, str] | None = None,
        *,
        source_label: str = "current process environment",
        colors_enabled: bool = True,
    ) -> None:
        self.screen = screen
        self.store = store
        self.colors_enabled = colors_enabled
        self.candidates = environment_import_candidates(dict(os.environ if environment is None else environment), store.values)
        self.source_label = source_label
        self.selected = 0
        self.scroll_offset = 0
        self.detail_offset = 0
        self.sort_mode = "name_asc"
        self.filter_scope = "both"
        self.filter_pattern = ""
        self.selected_sources: set[str] = set()
        self.status = "Space toggles a variable. A selects all shown. Enter imports. Esc returns to managed variables."
        self.status_attribute = curses.A_REVERSE | curses.A_BOLD if colors_enabled else curses.A_NORMAL
        self.source_attribute = curses.A_BOLD
        self.value_attribute = curses.A_NORMAL
        self.number_attribute = curses.A_NORMAL
        self.collision_attribute = curses.A_BOLD
        self.title_attribute = curses.A_BOLD
        self.control_label_attribute = curses.A_BOLD
        self.setting_attribute = curses.A_BOLD
        self.pattern_attribute = curses.A_NORMAL
        self.selected_attribute = curses.A_REVERSE if colors_enabled else curses.A_BOLD
        self.applied = False
        self.last_name: str | None = None

    def configure_colors(self) -> None:
        try:
            if not self.colors_enabled or not curses.has_colors():
                return
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_YELLOW)
            curses.init_pair(2, curses.COLOR_GREEN, background)
            curses.init_pair(3, curses.COLOR_YELLOW, background)
            curses.init_pair(4, curses.COLOR_BLUE, background)
            curses.init_pair(5, curses.COLOR_MAGENTA, background)
            curses.init_pair(6, curses.COLOR_RED, background)
            curses.init_pair(
                7,
                208 if getattr(curses, "COLORS", 0) >= 256 else curses.COLOR_YELLOW,
                background,
            )
            self.status_attribute = curses.color_pair(1) | curses.A_BOLD
            self.number_attribute = curses.color_pair(4)
            self.source_attribute = curses.color_pair(2) | curses.A_BOLD
            self.value_attribute = curses.color_pair(3)
            self.title_attribute = curses.color_pair(5) | curses.A_BOLD
            self.collision_attribute = curses.color_pair(6) | curses.A_BOLD
            self.control_label_attribute = curses.color_pair(7) | curses.A_BOLD
            self.setting_attribute = curses.color_pair(2) | curses.A_BOLD
            self.pattern_attribute = curses.color_pair(3)
        except curses.error:
            pass

    @staticmethod
    def catalog_row_limit(height: int) -> int:
        return catalog_layout(height)[0]

    @staticmethod
    def display_name(candidate: EnvironmentImportCandidate) -> str:
        return candidate.name or candidate.source_name

    @staticmethod
    def display_candidate_value(candidate: EnvironmentImportCandidate) -> str:
        if not candidate.selectable:
            return "(not importable)"
        assert candidate.name is not None and candidate.value is not None
        return display_value(candidate.name, candidate.value)

    def catalog_candidates(self) -> list[EnvironmentImportCandidate]:
        pattern = self.filter_pattern.casefold()
        candidates = [
            candidate
            for candidate in self.candidates
            if candidate.name not in self.store.values
            and (
                not pattern
                or (
                    self.filter_scope in {"name", "both"}
                    and pattern in self.display_name(candidate).casefold()
                )
                or (
                    self.filter_scope in {"value", "both"}
                    and pattern in self.display_candidate_value(candidate).casefold()
                )
            )
        ]
        self.selected_sources.intersection_update({candidate.source_name for candidate in candidates})
        if self.sort_mode == "name_asc":
            return sorted(candidates, key=lambda candidate: (self.display_name(candidate), candidate.source_name))
        if self.sort_mode == "name_desc":
            return sorted(
                candidates,
                key=lambda candidate: (self.display_name(candidate), candidate.source_name),
                reverse=True,
            )
        return sorted(
            candidates,
            key=lambda candidate: (self.display_candidate_value(candidate).casefold(), self.display_name(candidate)),
            reverse=self.sort_mode == "value_desc",
        )

    def _clamp_selection(self, candidates: list[EnvironmentImportCandidate]) -> None:
        self.selected = min(max(0, self.selected), max(0, len(candidates) - 1))

    def _ensure_visible(self, candidates: list[EnvironmentImportCandidate], visible_rows: int) -> None:
        self._clamp_selection(candidates)
        maximum_offset = max(0, len(candidates) - visible_rows)
        self.scroll_offset = min(max(0, self.scroll_offset), maximum_offset)
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + visible_rows:
            self.scroll_offset = self.selected - visible_rows + 1

    def current_candidate(self) -> EnvironmentImportCandidate | None:
        candidates = self.catalog_candidates()
        self._clamp_selection(candidates)
        return candidates[self.selected] if candidates else None

    def _select_source(self, source_name: str | None) -> None:
        candidates = self.catalog_candidates()
        if source_name is not None:
            for index, candidate in enumerate(candidates):
                if candidate.source_name == source_name:
                    self.selected = index
                    break
        self._clamp_selection(candidates)
        self.scroll_offset = 0
        self.detail_offset = 0

    def move_selection(self, distance: int) -> None:
        candidates = self.catalog_candidates()
        self._clamp_selection(candidates)
        if candidates:
            self.selected = min(max(0, self.selected + distance), len(candidates) - 1)
            self.detail_offset = 0


    def toggle_current(self) -> None:
        candidate = self.current_candidate()
        if candidate is None:
            self.status = "No environment variables match the current filter."
        elif not candidate.selectable:
            self.status = f"{candidate.source_name} cannot be imported: {candidate.error}"
        elif candidate.source_name in self.selected_sources:
            self.selected_sources.remove(candidate.source_name)
            self.status = f"{candidate.name} removed from the import selection."
        else:
            self.selected_sources.add(candidate.source_name)
            self.status = f"{candidate.name} selected for import."

    def toggle_all_shown(self) -> None:
        candidates = [candidate for candidate in self.catalog_candidates() if candidate.selectable]
        if not candidates:
            self.status = "No importable variables match the current filter."
            return
        sources = {candidate.source_name for candidate in candidates}
        if sources.issubset(self.selected_sources):
            self.selected_sources.difference_update(sources)
            self.status = f"Cleared {len(sources)} shown variable(s) from the import selection."
        else:
            self.selected_sources.update(sources)
            self.status = f"Selected all {len(sources)} importable variable(s) shown."

    def cycle_sort(self) -> None:
        current = self.current_candidate()
        modes = ("name_asc", "name_desc", "value_asc", "value_desc")
        self.sort_mode = modes[(modes.index(self.sort_mode) + 1) % len(modes)]
        self._select_source(None if current is None else current.source_name)
        self.status = f"Sort: {self.sort_mode.replace('_', ' ')}."

    def cycle_filter_scope(self) -> None:
        current = self.current_candidate()
        scopes = ("both", "name", "value")
        self.filter_scope = scopes[(scopes.index(self.filter_scope) + 1) % len(scopes)]
        self._select_source(None if current is None else current.source_name)
        self.status = f"Filter scope: {self.filter_scope}."

    def set_filter(self) -> None:
        current = self.current_candidate()
        raw_pattern = EnvmanTUI(self.screen, self.store).prompt("Import filter pattern (empty clears)")
        if raw_pattern is None:
            self.status = "Import filter unchanged."
            return
        self.filter_pattern = normalize_value(raw_pattern)
        self._select_source(None if current is None else current.source_name)
        self.status = "Import filter cleared." if not self.filter_pattern else "Import filter updated."

    def detail_lines(self, width: int) -> list[str]:
        candidate = self.current_candidate()
        if candidate is None:
            return ["Selected external variable: (none)"]
        name = self.display_name(candidate)
        state = {
            "add": "will be added",
            "collision": "will replace a managed variable",
            "unchanged": "already matches the managed value",
            "invalid": candidate.error or "cannot be imported",
        }[candidate.state]
        value = self.display_candidate_value(candidate)
        text = f"Source: {candidate.source_name} → {name} ({state})  Selected external value: {value}"
        available = max(1, width - 4)
        return [text[index : index + available] for index in range(0, len(text), available)] or [""]

    def draw_detail(
        self,
        width: int,
        first_row: int,
        visible_rows: int,
        detail_rows: int,
        horizontal_line: int,
    ) -> None:
        divider_row = first_row + visible_rows
        detail_start = divider_row + 1
        self.screen.hline(divider_row, 2, horizontal_line, width - 4)
        lines = self.detail_lines(width)
        self.detail_offset = min(self.detail_offset, max(0, len(lines) - detail_rows))
        candidate = self.current_candidate()
        if candidate is None:
            self.screen.addnstr(detail_start, 2, lines[self.detail_offset], width - 4, curses.A_DIM)
            return
        name = self.display_name(candidate)
        state = {
            "add": "will be added",
            "collision": "will replace a managed variable",
            "unchanged": "already matches the managed value",
            "invalid": candidate.error or "cannot be imported",
        }[candidate.state]
        name_attribute = (
            self.collision_attribute if candidate.state in {"collision", "invalid"} else self.source_attribute
        )
        draw_wrapped_segments(
            self.screen,
            detail_start,
            width,
            (
                ("Source: ", curses.A_DIM),
                (candidate.source_name, self.source_attribute),
                (" → ", curses.A_DIM),
                (name, name_attribute),
                (f" ({state})  Selected external value: ", curses.A_DIM),
                (self.display_candidate_value(candidate), self.value_attribute),
            ),
            line_offset=self.detail_offset,
            max_lines=detail_rows,
        )

    def scroll_detail(self, distance: int) -> None:
        lines = self.detail_lines(self.screen.getmaxyx()[1])
        self.detail_offset = min(max(0, self.detail_offset + distance), max(0, len(lines) - DETAIL_MIN_ROWS))

    def _draw_size_error(self, height: int, width: int) -> None:
        EnvmanTUI(self.screen, self.store)._draw_size_error(height, width)

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < MIN_TUI_HEIGHT or width < MIN_TUI_WIDTH:
            self._draw_size_error(height, width)
            return
        draw_colored_line(
            self.screen,
            TITLE_ROW,
            width,
            (("Envman · Import Preview", self.title_attribute),),
        )
        draw_colored_line(
            self.screen,
            SUBTITLE_ROW,
            width,
            (
                ("Esc", self.number_attribute | curses.A_BOLD),
                (" back · Source: ", curses.A_DIM),
                (self.source_label, self.source_attribute),
                (". Only variables not already managed are shown.", curses.A_DIM),
            ),
        )
        horizontal_line = getattr(curses, "ACS_HLINE", ord("-"))
        self.screen.hline(HEADER_DIVIDER_ROW, 2, horizontal_line, width - 4)
        sort_label = {
            "name_asc": "Name ↑",
            "name_desc": "Name ↓",
            "value_asc": "Value ↑",
            "value_desc": "Value ↓",
        }[self.sort_mode]
        draw_catalog_controls(
            self.screen,
            width,
            sort_label=sort_label,
            filter_scope=self.filter_scope,
            filter_pattern=self.filter_pattern,
            label_attribute=self.control_label_attribute,
            setting_attribute=self.setting_attribute,
            pattern_attribute=self.pattern_attribute,
            key_attribute=self.number_attribute | curses.A_BOLD,
        )
        candidates = self.catalog_candidates()
        visible_rows, first_row, detail_rows = catalog_layout(height)
        self._ensure_visible(candidates, visible_rows)
        draw_colored_line(
            self.screen,
            CATALOG_HINT_ROW,
            width,
            (
                (f"{len(candidates)} shown · ", curses.A_DIM),
                ("Space", self.number_attribute | curses.A_BOLD),
                (" toggles · ", curses.A_DIM),
                ("A", self.number_attribute | curses.A_BOLD),
                (" selects all shown · ", curses.A_DIM),
                ("Enter", self.number_attribute | curses.A_BOLD),
                (" imports", curses.A_DIM),
            ),
        )
        self.screen.hline(LIST_DIVIDER_ROW, 2, horizontal_line, width - 4)
        for index, candidate in enumerate(
            candidates[self.scroll_offset : self.scroll_offset + visible_rows],
            start=self.scroll_offset,
        ):
            row = first_row + index - self.scroll_offset
            focused = index == self.selected
            row_attribute = self.selected_attribute if focused else curses.A_NORMAL
            marker = "[*]" if candidate.source_name in self.selected_sources else "[ ]"
            state_marker = "! " if candidate.state == "collision" else ""
            value = self.display_candidate_value(candidate)
            column = 4
            remaining = width - 8
            text_capacity = max(1, remaining - len(marker) - len(state_marker) - 1)
            name_text = truncate_for_display(self.display_name(candidate), max(3, text_capacity // 2))
            value_text = truncate_for_display(value, max(0, text_capacity - len(name_text) - 3))
            name_attribute = self.collision_attribute if candidate.state in {"collision", "invalid"} else self.source_attribute
            for text, attribute in (
                (marker, self.source_attribute | row_attribute),
                (" ", row_attribute),
                (state_marker, self.collision_attribute | row_attribute),
                (name_text, name_attribute | row_attribute),
                (" = ", curses.A_DIM | row_attribute),
                (value_text, self.value_attribute | row_attribute),
            ):
                if remaining <= 0:
                    break
                self.screen.addnstr(row, column, text, remaining, attribute)
                used = min(len(text), remaining)
                column += used
                remaining -= used
        if not candidates:
            self.screen.addnstr(first_row, 4, "No external variables match the filter.", width - 8, curses.A_DIM)
        self.draw_detail(width, first_row, visible_rows, detail_rows, horizontal_line)
        self.screen.hline(height - 5, 2, horizontal_line, width - 4)
        draw_key_legend(
            self.screen,
            height - 4,
            width,
            (
                ("Space", "Toggle"),
                ("A", "ll"),
                ("Enter", "Import"),
                ("O", "rder"),
                ("F", "ilter"),
                ("M", "ode"),
            ),
            key_attribute=self.number_attribute | curses.A_BOLD,
            label_attribute=curses.A_DIM,
            separator="",
        )
        draw_key_legend(
            self.screen,
            height - 3,
            width,
            (
                ("[/]", "view"),
                ("Esc", "back"),
            ),
            key_attribute=self.number_attribute | curses.A_BOLD,
            label_attribute=curses.A_DIM,
            separator="",
        )
        status_width = width - 4
        self.screen.addnstr(
            height - 2,
            2,
            f" {self.status} ".ljust(status_width),
            status_width,
            self.status_attribute,
        )
        self.screen.refresh()

    def import_selected(self) -> bool:
        try:
            values, warnings, collisions = prepare_environment_import(
                self.candidates,
                self.selected_sources,
                self.store.values,
                allow_replace=True,
            )
        except StoreError as exc:
            self.status = str(exc)
            return False
        previous_values = self.store.values.copy()
        previous_lines = self.store.lines.copy()
        self.store.values.update(values)
        try:
            self.store.save()
        except StoreError as exc:
            self.store.values = previous_values
            self.store.lines = previous_lines
            self.status = f"Import was not saved: {exc}"
            return False
        self.applied = True
        self.last_name = sorted(values)[0] if values else None
        warning_text = f" {len(warnings)} advisory warning(s)." if warnings else ""
        collision_text = f" Replaced {len(collisions)} managed variable(s)." if collisions else ""
        self.status = f"Imported {len(values)} variable(s).{collision_text}{warning_text}"
        return True

    def run(self) -> bool:
        self.configure_colors()
        self.screen.keypad(True)
        while True:
            self.draw()
            key = self.screen.get_wch()
            if key in ("\x1b", 27):
                self.status = "Import cancelled. Returned to managed variable list."
                return False
            height, width = self.screen.getmaxyx()
            if height < MIN_TUI_HEIGHT or width < MIN_TUI_WIDTH:
                continue
            if key == " ":
                self.toggle_current()
            elif key in ("a", "A"):
                self.toggle_all_shown()
            elif key in ("\n", "\r", curses.KEY_ENTER):
                if self.import_selected():
                    return True
            elif key in ("o", "O"):
                self.cycle_sort()
            elif key in ("f", "F"):
                self.set_filter()
            elif key in ("m", "M"):
                self.cycle_filter_scope()
            elif key == curses.KEY_UP:
                self.move_selection(-1)
            elif key == curses.KEY_DOWN:
                self.move_selection(1)
            elif key == "[":
                self.scroll_detail(-1)
            elif key == "]":
                self.scroll_detail(1)



def run_tui(store: EnvironmentStore, *, colors_enabled: bool = True) -> bool:
    app: EnvmanTUI | None = None

    def wrapped(screen: curses.window) -> None:
        nonlocal app
        app = EnvmanTUI(screen, store, colors_enabled=colors_enabled)
        app.run()

    try:
        curses.wrapper(wrapped)
    except SystemExit:
        pass
    return bool(app and app.start_shell)


EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_INVALID = 2
EXIT_NOT_FOUND = 3


class CommandError(Exception):
    """A requested command is validly parsed but cannot be completed."""

    def __init__(self, message: str, exit_code: int = EXIT_INVALID) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Manage persistent user environment variables without opening the terminal UI.",
        epilog=(
            "Automation: use COMMAND --json for structured output and --force (or --yes) "
            "to accept advisory warnings. Required safety and input validation always apply.\n"
            "Examples: envman list --json | envman set API_KEY --stdin --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {app_version()}")
    parser.add_argument(
        "--nocolor",
        action="store_true",
        help="Launch the interactive TUI without curses color pairs.",
    )
    commands = parser.add_subparsers(dest="command", required=False, title="commands")

    def command(name: str, **kwargs: Any) -> argparse.ArgumentParser:
        subparser = commands.add_parser(name, **kwargs)
        subparser.add_argument(
            "--json",
            action="store_true",
            help="Emit a stable machine-readable result.",
        )
        return subparser

    command("init", help="Install shell loaders without adding a variable.")
    command("target", help="Show the managed configuration file location.")
    command("check", help="Validate the managed configuration.")
    update_parser = command("update", help="Check for or install a verified GitHub release update.")
    update_parser.add_argument("--check", action="store_true", help="Report whether an update is available without installing it.")

    list_parser = command("list", help="List managed variables.")
    list_parser.add_argument(
        "--reveal",
        action="store_true",
        help="Include sensitive values in output; use only in a secure caller.",
    )

    get_parser = command("get", help="Read one managed variable.")
    get_parser.add_argument("name")
    get_parser.add_argument(
        "--reveal",
        action="store_true",
        help="Include a sensitive value in output; use only in a secure caller.",
    )

    import_parser = command(
        "import",
        help="Preview or explicitly import variables from the current process environment.",
    )
    import_parser.add_argument("names", nargs="*", metavar="NAME", help="Preview or import only these names.")
    import_parser.add_argument("--all", action="store_true", help="Select every external variable when used with --apply.")
    import_parser.add_argument("--apply", action="store_true", help="Persist the selected external variables.")
    import_parser.add_argument(
        "--replace",
        action="store_true",
        help="Allow --apply to replace selected managed-name collisions.",
    )
    import_parser.add_argument(
        "--force",
        "--yes",
        action="store_true",
        help="Accept and suppress advisory warnings; does not bypass validation or collision protection.",
    )

    export_parser = command(
        "export",
        help=f"Write all managed variables as an encrypted JSON backup using ${BACKUP_KEY_ENV}.",
    )
    export_parser.add_argument(
        "destination",
        nargs="?",
        help="Output file, or an existing output directory. Defaults to envman-YYYYMMDDTHHMMSSZ.json in the current directory.",
    )

    backup_import_parser = command(
        "import-backup",
        help=f"Preview or explicitly import variables from an encrypted JSON backup using ${BACKUP_KEY_ENV}.",
    )
    backup_import_parser.add_argument("path", help="Encrypted backup JSON file.")
    backup_import_parser.add_argument("names", nargs="*", metavar="NAME", help="Preview or import only these names.")
    backup_import_parser.add_argument("--all", action="store_true", help="Select every backup variable when used with --apply.")
    backup_import_parser.add_argument("--apply", action="store_true", help="Persist the selected backup variables.")
    backup_import_parser.add_argument(
        "--replace",
        action="store_true",
        help="Allow --apply to replace selected managed-name collisions.",
    )
    backup_import_parser.add_argument(
        "--force",
        "--yes",
        action="store_true",
        help="Accept and suppress advisory warnings; does not bypass validation or collision protection.",
    )

    set_parser = command("set", help="Create or replace one managed variable.")
    set_parser.add_argument("name")
    value_source = set_parser.add_mutually_exclusive_group(required=True)
    value_source.add_argument(
        "--value",
        help="Literal value or an existing managed variable name to resolve.",
    )
    value_source.add_argument("--stdin", action="store_true", help="Read a literal value from standard input.")
    value_source.add_argument("--from", dest="from_name", metavar="NAME", help="Copy the value from a managed variable.")
    set_parser.add_argument(
        "--force",
        "--yes",
        action="store_true",
        help="Accept and suppress advisory warnings; does not bypass required validation.",
    )

    unset_parser = command("unset", help="Remove one managed variable.")
    unset_parser.add_argument("name")

    rename_parser = command("rename", help="Rename one managed variable.")
    rename_parser.add_argument("old_name")
    rename_parser.add_argument("new_name")

    validate_parser = command("validate", help="Validate a variable without saving it.")
    validate_parser.add_argument("name")
    value_source = validate_parser.add_mutually_exclusive_group(required=True)
    value_source.add_argument(
        "--value",
        help="Literal value or an existing managed variable name to resolve.",
    )
    value_source.add_argument("--stdin", action="store_true", help="Read a literal value from standard input.")
    value_source.add_argument("--from", dest="from_name", metavar="NAME", help="Validate a copied managed value.")
    validate_parser.add_argument(
        "--force",
        "--yes",
        action="store_true",
        help="Accept and suppress advisory warnings; does not bypass required validation.",
    )
    return parser


def cli_name(raw_name: str) -> str:
    name = normalize_name(raw_name)
    try:
        validate_name(name)
        name = name.upper()
    except StoreError as exc:
        raise CommandError(str(exc)) from exc
    return name


def cli_value(
    arguments: argparse.Namespace,
    name: str,
    store: EnvironmentStore,
) -> tuple[str, tuple[str, ...]]:
    def complete(value: str, warnings: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        warnings = append_credential_warning(name, value, warnings)
        return value, () if arguments.force else warnings

    if arguments.from_name:
        source_name = existing_cli_name(store, arguments.from_name)
        try:
            return complete(*prepare_copied_value(name, source_name, store.values))
        except StoreError as exc:
            raise CommandError(str(exc)) from exc
    if arguments.stdin:
        raw_value = sys.stdin.read(MAX_VALUE_LENGTH + 1)
        try:
            return complete(*prepare_value(name, raw_value))
        except StoreError as exc:
            raise CommandError(str(exc)) from exc

    raw_value = arguments.value
    source_name = referenced_value_name(raw_value, store.values)
    if source_name is not None and not is_secret_reference_name(name):
        try:
            return complete(*prepare_copied_value(name, source_name, store.values))
        except StoreError as exc:
            raise CommandError(str(exc)) from exc
    if not is_secret_reference_name(name) and (
        is_secret_name(name) or is_secret_value(name, raw_value)
    ):
        raise CommandError(
            "Sensitive values must be supplied with --stdin, not --value.",
        )
    try:
        return complete(*prepare_entered_value(name, raw_value, store.values))
    except StoreError as exc:
        raise CommandError(str(exc)) from exc


def cli_import_name(raw_name: str) -> str:
    try:
        validate_name(raw_name)
    except StoreError as exc:
        raise CommandError(str(exc)) from exc
    return raw_name


def cli_variable(name: str, value: str, reveal: bool = False) -> dict[str, Any]:
    sensitive = is_secret_value(name, value)
    return {
        "name": name,
        "sensitive": sensitive,
        "value": value if reveal or not sensitive else display_value(name, value),
    }


def cli_import_candidate(candidate: EnvironmentImportCandidate, *, source: str = "environment") -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": source,
        "source_name": candidate.source_name,
        "state": candidate.state,
    }
    if not candidate.selectable:
        result["error"] = candidate.error
        return result
    assert candidate.name is not None and candidate.value is not None
    result["variable"] = cli_variable(candidate.name, candidate.value)
    result["warnings"] = list(candidate.warnings)
    return result


def selected_environment_import_sources(
    arguments: argparse.Namespace,
    candidates: list[EnvironmentImportCandidate],
    *,
    source_label: str = "current environment",
) -> set[str]:
    if not arguments.names:
        return {candidate.source_name for candidate in candidates}
    requested = {cli_import_name(name) for name in arguments.names}
    sources = {
        candidate.source_name
        for candidate in candidates
        if candidate.name is not None and candidate.name in requested
    }
    matched_names = {
        candidate.name
        for candidate in candidates
        if candidate.source_name in sources and candidate.name is not None
    }
    missing = requested - matched_names
    if missing:
        raise CommandError(f"Not present in the {source_label}: {', '.join(sorted(missing))}", EXIT_NOT_FOUND)
    return sources


def emit_cli(result: dict[str, Any], as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(text)


def persist_cli_change(
    store: EnvironmentStore,
    previous_values: dict[str, str],
    previous_lines: list[str],
) -> None:
    try:
        store.save()
    except StoreError:
        store.values = previous_values
        store.lines = previous_lines
        raise


def existing_cli_name(store: EnvironmentStore, raw_name: str) -> str:
    name = cli_name(raw_name)
    if name not in store.values:
        raise CommandError(f"{name} is not managed.", EXIT_NOT_FOUND)
    return name


def emit_warnings(warnings: tuple[str, ...], as_json: bool) -> None:
    if not as_json:
        for warning in warnings:
            if os.path.isabs(warning):
                warning = f"PATH does not exist: {warning}"
            print(f"envman: warning: {warning}", file=sys.stderr)


def run_cli_import(
    arguments: argparse.Namespace,
    store: EnvironmentStore,
    environment: dict[str, str],
    *,
    source: str,
    source_label: str,
) -> int:
    if arguments.names and arguments.all:
        raise CommandError("Use explicit names or --all, not both.")
    candidates = environment_import_candidates(environment, store.values)
    selected_sources = selected_environment_import_sources(
        arguments,
        candidates,
        source_label=source_label,
    )
    selected_candidates = sorted(
        (candidate for candidate in candidates if candidate.source_name in selected_sources),
        key=lambda candidate: candidate.source_name,
    )
    records = [cli_import_candidate(candidate, source=source) for candidate in selected_candidates]
    if not arguments.apply:
        emit_cli(
            {"action": "preview", "variables": records},
            arguments.json,
            "\n".join(
                (
                    f"{record['variable']['name']}={record['variable']['value']} [{record['state']}]"
                    if "variable" in record
                    else f"{record['source_name']} [invalid: {record['error']}]"
                )
                for record in records
            ),
        )
        return EXIT_SUCCESS
    if not arguments.names and not arguments.all:
        raise CommandError("--apply requires at least one NAME or --all.")
    import_sources = selected_sources
    if arguments.all:
        import_sources = {
            candidate.source_name
            for candidate in selected_candidates
            if candidate.selectable
        }
    if not import_sources:
        raise CommandError("No importable environment variables were selected.")
    try:
        values, warnings, collisions = prepare_environment_import(
            candidates,
            import_sources,
            store.values,
            allow_replace=arguments.replace,
        )
    except StoreError as exc:
        raise CommandError(str(exc)) from exc
    if arguments.force:
        warnings = ()
        for record in records:
            record.pop("warnings", None)
    previous_values = store.values.copy()
    previous_lines = store.lines.copy()
    store.values.update(values)
    try:
        persist_cli_change(store, previous_values, previous_lines)
    except StoreError as exc:
        raise CommandError(str(exc), EXIT_FAILURE) from exc
    result = {
        "action": "imported",
        "collisions": sorted(collisions),
        "variables": records,
        "warnings": list(warnings),
    }
    emit_cli(
        result,
        arguments.json,
        f"Imported {len(values)} variable(s); replaced {len(collisions)} managed variable(s).",
    )
    emit_warnings(warnings, arguments.json)
    return EXIT_SUCCESS

def run_update_cli(arguments: argparse.Namespace) -> int:
    try:
        result = update_release(check_only=arguments.check)
    except ReleaseProtocolError as exc:
        message = str(exc)
        exit_code = EXIT_FAILURE if message.startswith(("Could not", "Installation failed", "Update failed", "Installed")) else EXIT_INVALID
        raise CommandError(message, exit_code) from exc
    status = str(result["status"])
    if status == "current":
        text = f"Envman {result['installed_version']} is current."
    elif status == "update-available":
        text = f"Envman {result['available_version']} is available (installed: {result['installed_version']})."
    else:
        text = f"Updated Envman from {result['installed_version']} to {result['available_version']}."
    emit_cli(result, arguments.json, text)
    return EXIT_SUCCESS


def run_cli(arguments: argparse.Namespace, store: EnvironmentStore) -> int:
    command = arguments.command
    if command == "init":
        store.install_loaders()
        emit_cli(
            {"loader": str(store.loader), "target": str(store.target)},
            arguments.json,
            f"Loaders installed for {store.target}",
        )
        return EXIT_SUCCESS
    if command == "target":
        emit_cli(
            {"exists": store.target.exists(), "target": str(store.target)},
            arguments.json,
            str(store.target),
        )
        return EXIT_SUCCESS
    if command == "check":
        emit_cli(
            {"target": str(store.target), "variables": len(store.values)},
            arguments.json,
            f"OK: {len(store.values)} variable(s) in {store.target}",
        )
        return EXIT_SUCCESS
    if command == "list":
        variables = [
            cli_variable(name, store.values[name], arguments.reveal)
            for name in sorted(store.values)
        ]
        emit_cli(
            {"variables": variables},
            arguments.json,
            "\n".join(f"{variable['name']}={variable['value']}" for variable in variables),
        )
        return EXIT_SUCCESS
    if command == "export":
        try:
            destination = encrypted_backup_destination(arguments.destination)
            envelope = write_encrypted_backup(destination, store.values)
        except StoreError as exc:
            raise CommandError(str(exc), EXIT_FAILURE) from exc
        emit_cli(
            {
                "action": "exported",
                "envman_version": envelope["envman_version"],
                "path": str(destination),
                "schema": envelope["schema"],
                "schema_version": envelope["schema_version"],
                "variables": len(store.values),
            },
            arguments.json,
            f"Exported {len(store.values)} encrypted variable(s) to {destination}",
        )
        return EXIT_SUCCESS
    if command == "import":
        return run_cli_import(
            arguments,
            store,
            dict(os.environ),
            source="environment",
            source_label="current environment",
        )
    if command == "import-backup":
        try:
            environment = encrypted_backup_variables(Path(arguments.path).expanduser())
        except StoreError as exc:
            raise CommandError(str(exc), EXIT_FAILURE) from exc
        return run_cli_import(
            arguments,
            store,
            environment,
            source="encrypted-backup",
            source_label="encrypted backup",
        )
    if command == "get":
        name = existing_cli_name(store, arguments.name)
        variable = cli_variable(name, store.values[name], arguments.reveal)
        emit_cli(
            {"variable": variable},
            arguments.json,
            str(variable["value"]),
        )
        return EXIT_SUCCESS
    if command in {"set", "validate"}:
        name = cli_name(arguments.name)
        value, warnings = cli_value(arguments, name, store)
        variable = cli_variable(name, value)
        if command == "set":
            previous_values = store.values.copy()
            previous_lines = store.lines.copy()
            store.values[name] = value
            persist_cli_change(store, previous_values, previous_lines)
        result = {"variable": variable, "warnings": list(warnings)}
        action = "Saved" if command == "set" else "Valid"
        emit_cli(result, arguments.json, f"{action}: {name}={variable['value']}")
        emit_warnings(warnings, arguments.json)
        return EXIT_SUCCESS
    if command == "unset":
        name = existing_cli_name(store, arguments.name)
        previous_values = store.values.copy()
        previous_lines = store.lines.copy()
        value = store.values.pop(name)
        persist_cli_change(store, previous_values, previous_lines)
        variable = cli_variable(name, value)
        emit_cli({"variable": variable}, arguments.json, f"Removed: {name}")
        return EXIT_SUCCESS
    if command == "rename":
        old_name = existing_cli_name(store, arguments.old_name)
        new_name = cli_name(arguments.new_name)
        if new_name in store.values and new_name != old_name:
            raise CommandError(f"{new_name} is already managed.")
        previous_values = store.values.copy()
        previous_lines = store.lines.copy()
        value = store.values[old_name]
        try:
            validate_rename_sensitivity(old_name, new_name, value)
        except StoreError as exc:
            raise CommandError(str(exc)) from exc
        value = store.values.pop(old_name)
        store.values[new_name] = value
        persist_cli_change(store, previous_values, previous_lines)
        variable = cli_variable(new_name, value)
        emit_cli(
            {"old_name": old_name, "variable": variable},
            arguments.json,
            f"Renamed: {old_name} -> {new_name}",
        )
        return EXIT_SUCCESS
    raise CommandError(f"Unsupported command: {command}", EXIT_FAILURE)


def main() -> NoReturn:
    arguments = sys.argv[1:]
    colors_enabled = True
    if arguments:
        if arguments[0] == "--check":
            arguments[0] = "check"
        parser = build_cli_parser()
        parsed = parser.parse_args(arguments)
        if parsed.command is not None:
            if parsed.nocolor:
                parser.error("--nocolor is only available when launching the interactive TUI.")
            try:
                if parsed.command == "update":
                    raise SystemExit(run_update_cli(parsed))
                home = Path.home()
                store = EnvironmentStore(home, configuration_home(home))
                store.load()
                raise SystemExit(run_cli(parsed, store))
            except CommandError as exc:
                print(f"envman: {exc}", file=sys.stderr)
                raise SystemExit(exc.exit_code)
            except StoreError as exc:
                print(f"envman: {exc}", file=sys.stderr)
                raise SystemExit(EXIT_FAILURE)
        if not parsed.nocolor:
            parser.error("a command is required")
        colors_enabled = False
    try:
        home = Path.home()
        store = EnvironmentStore(home, configuration_home(home))
        store.load()
    except StoreError as exc:
        print(f"envman: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_FAILURE)
    if run_tui(store, colors_enabled=colors_enabled):
        try:
            store.validate_child_environment()
            environment = store.child_environment()
            shell = environment.get("SHELL", "/bin/bash")
            if not os.path.isfile(shell) or not os.access(shell, os.X_OK):
                raise StoreError(f"cannot start configured shell: {shell}")
            os.execvpe(shell, [Path(shell).name, "-i"], environment)
        except (OSError, StoreError) as exc:
            print(f"envman: {exc}", file=sys.stderr)
            raise SystemExit(EXIT_FAILURE) from exc
    raise SystemExit(EXIT_SUCCESS)


if __name__ == "__main__":
    main()
