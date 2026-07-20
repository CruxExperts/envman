#!/usr/bin/env python3
"""Check and plan Envman's patch-default Conventional Commit release policy."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
REVERT_TARGET = re.compile(r"This reverts commit (?P<sha>[0-9a-f]{7,40})\.", re.IGNORECASE)
CONVENTIONAL = re.compile(r"^(?:[a-z]+)(?:\([^)]+\))?!?: .+")
RELEASE_TYPE = re.compile(r"^Release-Type:\s*(major|minor|patch|none)\s*$", re.MULTILINE | re.IGNORECASE)
README_VERSION = re.compile(r"^\*\*Version:\*\* (?P<version>[^\s]+)$", re.MULTILINE)


def run_git(*args: str, allow_failure: bool = False) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode and not allow_failure:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.rstrip("\r\n")


def version() -> str:
    value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if SEMVER.fullmatch(value) is None:
        raise ValueError("VERSION must be strict MAJOR.MINOR.PATCH SemVer")
    return value


def latest_tag() -> str | None:
    value = run_git("describe", "--tags", "--match", "v[0-9]*", "--abbrev=0", allow_failure=True)
    return value or None


def commit_records(tag: str | None) -> list[tuple[str, str, str]]:
    revision = f"{tag}..HEAD" if tag else "HEAD"
    raw = run_git("log", "--format=%H%x1f%s%x1f%b%x1e", revision)
    return [
        tuple(record.split("\x1f", 2))
        for record in raw.split("\x1e")
        if record and record.count("\x1f") == 2
    ]


def active_records(records: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Drop a Revert commit and the exact commit it fully reverts."""
    reverted = {
        match.group("sha")
        for _sha, subject, body in records
        if subject.lower().startswith("revert:") or subject.startswith("Revert ")
        for match in REVERT_TARGET.finditer(body)
    }
    return [
        record
        for record in records
        if not (record[1].lower().startswith("revert:") or record[1].startswith("Revert "))
        and not any(record[0].startswith(target) for target in reverted)
    ]


def plan() -> dict[str, object]:
    current = version()
    tag = latest_tag()
    if tag is None:
        return {"current": current, "target": current, "bump": "none", "raw_bump": "none", "warnings": [], "reason": "initial-version-held-until-v0.1.0"}
    warnings: list[str] = []
    intents: list[str] = []
    for _sha, subject, body in active_records(commit_records(tag)):
        if subject.startswith(("Merge ", "chore: sync release version")):
            continue
        if CONVENTIONAL.fullmatch(subject) is None:
            warnings.append(f"non-Conventional Commit: {subject}")
            continue
        explicit = RELEASE_TYPE.search(subject + "\n" + body)
        breaking = "!:" in subject or "BREAKING CHANGE:" in body or "BREAKING-CHANGE:" in body
        if breaking and explicit is None:
            warnings.append(f"breaking intent needs Release-Type: {subject}")
        intents.append(explicit.group(1).lower() if explicit else "patch")
    order = {"none": 0, "patch": 1, "minor": 2, "major": 3}
    bump = max(intents or ["none"], key=order.__getitem__)
    base = tag.removeprefix("v")
    if SEMVER.fullmatch(base) is None:
        raise ValueError("latest release tag must use strict vMAJOR.MINOR.PATCH SemVer")
    major, minor, patch = (int(part) for part in base.split("."))
    target = base if bump == "none" else f"{major + 1}.0.0" if bump == "major" else f"{major}.{minor + 1}.0" if bump == "minor" else f"{major}.{minor}.{patch + 1}"
    return {"current": current, "target": target, "bump": bump, "raw_bump": bump, "warnings": warnings, "tag": tag}


def check() -> int:
    current = version()
    match = README_VERSION.search((ROOT / "README.md").read_text(encoding="utf-8"))
    if match is None or match.group("version") != current:
        raise ValueError("README version display must equal VERSION")
    return 0


def sync() -> int:
    current = version()
    readme = ROOT / "README.md"
    original = readme.read_text(encoding="utf-8")
    updated, count = README_VERSION.subn(f"**Version:** {current}", original)
    if count != 1:
        raise ValueError("README must contain exactly one version display")
    readme.write_text(updated, encoding="utf-8")
    return check()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "plan", "sync"))
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return check()
        if args.command == "sync":
            return sync()
        result = plan()
        print(json.dumps(result, sort_keys=True))
        return 1 if result["warnings"] else 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"version: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
