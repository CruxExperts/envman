#!/usr/bin/env python3
"""Sync Envman's agent skill targets from a pinned LocalSetup release."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import pprint
import re
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "src" / "envman" / "_release_protocol.py"
BEGIN = "# BEGIN GENERATED LOCALSETUP SKILL TARGETS"
END = "# END GENERATED LOCALSETUP SKILL TARGETS"
BLOCK = re.compile(rf"(?ms)^{re.escape(BEGIN)}$.*?^{re.escape(END)}$")
LATEST_RELEASE_URL = "https://api.github.com/repos/CruxExperts/localsetup/releases/latest"
MAX_RELEASE_RESPONSE = 1 * 1024 * 1024
MAX_SOURCE_FILE = 4 * 1024 * 1024


def _default_source_root() -> Path:
    configured = os.environ.get("LOCALSETUP_SOURCE_ROOT")
    if configured:
        return Path(configured).expanduser()
    try:
        output = subprocess.run(
            ["localsetup", "path", "source-root"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(
            "LocalSetup source root is unavailable; pass --source-root or set LOCALSETUP_SOURCE_ROOT."
        ) from exc
    if not output or "\n" in output or "\r" in output:
        raise ValueError("localsetup path source-root returned an invalid path.")
    return Path(output).expanduser()


def _load_yaml(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"could not parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping.")
    return payload


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings.")
    return tuple(value)


def _validate_paths(paths: tuple[str, ...], scope: str, label: str) -> None:
    for value in paths:
        candidate = value[2:] if value.startswith("~/") else value
        parts = Path(candidate).parts
        if not parts or any(part in {"", ".", ".."} for part in parts) or Path(candidate).is_absolute():
            raise ValueError(f"{label} contains an unsafe path: {value}")
        if scope == "global" and not value.startswith("~/"):
            raise ValueError(f"{label} global paths must start with ~/: {value}")
        if scope == "repository" and value.startswith("~/"):
            raise ValueError(f"{label} repository paths must be relative: {value}")


def _historical_paths(source_root: Path) -> dict[str, tuple[str, ...]]:
    path = source_root / "ls" / "core" / "client_registry" / "historical.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ValueError(f"could not parse {path}: {exc}") from exc
    value: object | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "HISTORICAL_ADAPTERS" and node.value is not None:
                value = ast.literal_eval(node.value)
                break
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not define HISTORICAL_ADAPTERS as a literal mapping.")
    result: dict[str, tuple[str, ...]] = {}
    for target, transitions in value.items():
        if not isinstance(target, str) or not isinstance(transitions, tuple):
            raise ValueError(f"{path} contains invalid historical adapter data.")
        rows: list[str] = []
        for transition in transitions:
            if not isinstance(transition, dict) or not isinstance(transition.get("path"), str):
                raise ValueError(f"{path} contains invalid historical adapter data.")
            rows.append(transition["path"])
        result[target] = tuple(rows)
    return result


def _catalog(source_root: Path) -> tuple[str, str, str, dict[str, dict[str, tuple[str, ...]]]]:
    version_path = source_root / "VERSION"
    clients_path = source_root / "ls" / "config" / "clients.yaml"
    platforms_path = source_root / "ls" / "config" / "platforms.yaml"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"could not read {version_path}: {exc}") from exc
    if re.fullmatch(r"[1-9]\d*\.\d+\.\d+", version) is None:
        raise ValueError(f"{version_path} must contain strict stable SemVer.")
    clients = _load_yaml(clients_path)
    platforms = _load_yaml(platforms_path)
    rows = platforms.get("platforms")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{platforms_path} must contain a non-empty platforms list.")

    targets: dict[str, dict[str, tuple[str, ...]]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"{platforms_path} contains an invalid platform row.")
        target = row["id"]
        if target in targets:
            raise ValueError(f"{platforms_path} contains duplicate platform id: {target}")
        targets[target] = {
            "repository_write": _string_list(row.get("repo_paths"), f"{target}.repo_paths"),
            "global_write": _string_list(row.get("global_paths"), f"{target}.global_paths"),
            "repository_discover": (),
            "global_discover": (),
        }

    families = clients.get("families")
    if not isinstance(families, list):
        raise ValueError(f"{clients_path} must contain a families list.")
    for family in families:
        if not isinstance(family, dict) or not isinstance(family.get("variants"), list):
            raise ValueError(f"{clients_path} contains an invalid client family.")
        for variant in family["variants"]:
            if not isinstance(variant, dict) or not isinstance(variant.get("compatibility"), dict):
                continue
            compatibility = variant["compatibility"]
            target = compatibility.get("platform_id")
            integration = variant.get("integration")
            if target not in targets or not isinstance(integration, dict) or integration.get("lifecycle") != "active":
                continue
            skills = variant.get("skills")
            if not isinstance(skills, dict):
                raise ValueError(f"{clients_path} has no skill surfaces for {target}.")
            for scope, prefix in (("repo", "repository"), ("global", "global")):
                surface = skills.get(scope)
                if not isinstance(surface, dict) or surface.get("status") != "supported":
                    raise ValueError(f"{clients_path} has no supported {scope} skill surface for {target}.")
                discovered = _string_list(surface.get("paths"), f"{target}.skills.{scope}.paths")
                targets[target][f"{prefix}_discover"] = tuple(
                    dict.fromkeys((*targets[target][f"{prefix}_discover"], *discovered))
                )

    for target, historical in _historical_paths(source_root).items():
        if target in targets:
            targets[target]["repository_discover"] = tuple(
                dict.fromkeys((*targets[target]["repository_discover"], *historical))
            )

    for target, record in targets.items():
        for key, paths in record.items():
            scope = "global" if key.startswith("global") else "repository"
            _validate_paths(paths, scope, f"{target}.{key}")
            if not paths:
                raise ValueError(f"{target}.{key} must not be empty.")

    clients_hash = hashlib.sha256(clients_path.read_bytes()).hexdigest()
    platforms_hash = hashlib.sha256(platforms_path.read_bytes()).hexdigest()
    return version, clients_hash, platforms_hash, targets


def _latest_release_version() -> str:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "envman-localsetup-sync"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        LATEST_RELEASE_URL,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(MAX_RELEASE_RESPONSE + 1)
    except OSError as exc:
        raise ValueError(f"could not read the latest LocalSetup release: {exc}") from exc
    if len(raw) > MAX_RELEASE_RESPONSE:
        raise ValueError("latest LocalSetup release response exceeds 1 MiB.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"latest LocalSetup release response is invalid: {exc}") from exc
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    if not isinstance(tag, str) or re.fullmatch(r"v[1-9]\d*\.\d+\.\d+", tag) is None:
        raise ValueError("latest LocalSetup release does not have a stable SemVer tag.")
    return tag.removeprefix("v")


def _download_latest_source(destination: Path) -> Path:
    version = _latest_release_version()
    files = (
        "VERSION",
        "ls/config/clients.yaml",
        "ls/config/platforms.yaml",
        "ls/core/client_registry/historical.py",
    )
    base = f"https://raw.githubusercontent.com/CruxExperts/localsetup/v{version}/"
    for relative in files:
        headers = {"User-Agent": "envman-localsetup-sync"}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(base + relative, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read(MAX_SOURCE_FILE + 1)
        except OSError as exc:
            raise ValueError(f"could not download LocalSetup {relative}: {exc}") from exc
        if len(raw) > MAX_SOURCE_FILE:
            raise ValueError(f"LocalSetup {relative} exceeds 4 MiB.")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return destination


def _render(source_root: Path, verify_latest: bool) -> str:
    version, clients_hash, platforms_hash, targets = _catalog(source_root)
    if verify_latest:
        latest = _latest_release_version()
        if version != latest:
            raise ValueError(f"Envman pins LocalSetup {version}, but the latest stable release is {latest}.")
    source_url = f"https://github.com/CruxExperts/localsetup/tree/v{version}"
    mapping = pprint.pformat(targets, sort_dicts=True, width=110)
    return "\n".join(
        (
            BEGIN,
            f'LOCALSETUP_COMPATIBILITY_VERSION = "{version}"',
            f'LOCALSETUP_COMPATIBILITY_SOURCE = "{source_url}"',
            f'LOCALSETUP_CLIENTS_SHA256 = "{clients_hash}"',
            f'LOCALSETUP_PLATFORMS_SHA256 = "{platforms_hash}"',
            f"LOCALSETUP_SKILL_TARGETS = {mapping}",
            END,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source-root", type=Path, help="Pinned LocalSetup source checkout.")
    source.add_argument(
        "--github-latest",
        action="store_true",
        help="Read the latest stable LocalSetup projection directly from GitHub.",
    )
    parser.add_argument("--check", action="store_true", help="Fail when the committed target catalog is stale.")
    parser.add_argument(
        "--verify-latest",
        action="store_true",
        help="Require the pinned source version to equal GitHub's latest stable LocalSetup release.",
    )
    arguments = parser.parse_args(argv)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if arguments.github_latest:
            temporary = tempfile.TemporaryDirectory(prefix="envman-localsetup-")
            source_root = _download_latest_source(Path(temporary.name)).resolve(strict=True)
        else:
            source_root = (arguments.source_root or _default_source_root()).resolve(strict=True)
        source = PROTOCOL.read_text(encoding="utf-8")
        rendered = _render(source_root, arguments.verify_latest)
        if len(BLOCK.findall(source)) != 1:
            raise ValueError(f"{PROTOCOL} must contain exactly one generated LocalSetup target block.")
        expected = BLOCK.sub(rendered, source)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"sync_localsetup_skill_targets.py: {exc}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()
    if arguments.check:
        if source != expected:
            print(f"{PROTOCOL} has stale LocalSetup skill targets; run {Path(__file__).name}.", file=sys.stderr)
            return 1
        return 0
    if source != expected:
        PROTOCOL.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
