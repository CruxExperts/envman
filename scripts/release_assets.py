#!/usr/bin/env python3
"""Build release-manifest assets from a verified Envman distribution directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "CruxExperts/envman"
SKILL_SOURCE = ROOT / ".agents" / "skills" / "envman-environment-variable-manager" / "SKILL.md"
SKILL_FILENAME = "envman-environment-variable-manager-skill.md"
SKILL_LOCK_PATTERN = re.compile(
    r"(?m)^<!--\s*envman-skill-lock:\s*version=(?P<version>\d+\.\d+\.\d+)\s+source=src/envman/cli\.py\s*-->\s*$"
)
LEGACY_MANIFEST_FILENAME = "release-manifest.json"
CURRENT_MANIFEST_FILENAME = "release-manifest-v2.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def skill_bytes(version: str) -> bytes:
    expected_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != expected_version:
        raise ValueError(f"release version {version} must equal VERSION {expected_version}")
    try:
        raw = SKILL_SOURCE.read_bytes()
        text = raw.decode("utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"canonical agent skill is missing: {SKILL_SOURCE}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("canonical agent skill must be UTF-8") from exc
    markers = list(SKILL_LOCK_PATTERN.finditer(text))
    if len(markers) != 1 or markers[0].group("version") != version:
        raise ValueError("canonical agent skill is not locked to the requested release")
    return raw


def assets(version: str, output: Path) -> dict[str, dict[str, object]]:
    base = f"https://github.com/{REPOSITORY}/releases/download/v{version}/"
    wheel = next(output.glob("envman-*.whl"), None)
    if wheel is None:
        raise ValueError("release output must contain one Envman wheel")
    constraints = output / "runtime-constraints.txt"
    if not constraints.is_file():
        raise ValueError("release output must contain runtime-constraints.txt")
    raw_skill = skill_bytes(version)
    skill = output / SKILL_FILENAME
    skill.write_bytes(raw_skill)
    return {
        "wheel": {"filename": wheel.name, "url": base + wheel.name, "sha256": sha256(wheel), "size": wheel.stat().st_size},
        "runtime_constraints": {"filename": constraints.name, "url": base + constraints.name, "sha256": sha256(constraints), "size": constraints.stat().st_size},
        "skill": {"filename": skill.name, "url": base + skill.name, "sha256": sha256(skill), "size": skill.stat().st_size},
    }


def runtime_constraints() -> list[str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"].lower(): package for package in lock["package"]}
    pending = ["cryptography"]
    resolved: set[str] = set()
    while pending:
        name = pending.pop().lower()
        if name in resolved:
            continue
        package = packages.get(name)
        if package is None or "version" not in package:
            raise ValueError(f"runtime package is missing from uv.lock: {name}")
        resolved.add(name)
        pending.extend(dependency["name"] for dependency in package.get("dependencies", []))
    return [f"{name}=={packages[name]['version']}" for name in sorted(resolved)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "runtime-constraints.txt").write_text("\n".join(runtime_constraints()) + "\n", encoding="utf-8")
    manifest = {
        "schema": "envman.release-manifest",
        "schema_version": 1,
        "version": args.version,
        "repository": REPOSITORY,
        "compatibility": {"python": ">=3.12,<3.13", "platform": "linux-x86_64", "uv": ">=0.11,<0.12"},
        "assets": assets(args.version, output),
    }
    legacy_manifest = {**manifest, "assets": {key: value for key, value in manifest["assets"].items() if key != "skill"}}
    (output / LEGACY_MANIFEST_FILENAME).write_text(json.dumps(legacy_manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    (output / CURRENT_MANIFEST_FILENAME).write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    checksums = [f"{sha256(path)}  {path.name}" for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
