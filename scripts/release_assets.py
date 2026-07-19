#!/usr/bin/env python3
"""Build release-manifest assets from a verified Envman distribution directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "CruxExperts/envman"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assets(version: str, output: Path) -> dict[str, dict[str, object]]:
    base = f"https://github.com/{REPOSITORY}/releases/download/v{version}/"
    wheel = next(output.glob("envman-*.whl"), None)
    if wheel is None:
        raise ValueError("release output must contain one Envman wheel")
    constraints = output / "runtime-constraints.txt"
    if not constraints.is_file():
        raise ValueError("release output must contain runtime-constraints.txt")
    return {
        "wheel": {"filename": wheel.name, "url": base + wheel.name, "sha256": sha256(wheel), "size": wheel.stat().st_size},
        "runtime_constraints": {"filename": constraints.name, "url": base + constraints.name, "sha256": sha256(constraints), "size": constraints.stat().st_size},
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
    (output / "release-manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    checksums = [f"{sha256(path)}  {path.name}" for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
