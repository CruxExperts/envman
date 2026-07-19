#!/usr/bin/env python3
"""Validate that the machine and human documentation indexes agree."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    index = yaml.safe_load((ROOT / "docs" / "index.yaml").read_text(encoding="utf-8"))
    documents = index.get("documents") if isinstance(index, dict) else None
    if not isinstance(documents, list):
        raise SystemExit("docs/index.yaml must contain a documents list")
    seen: set[str] = set()
    human = (ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("path"), str):
            raise SystemExit("each documentation index entry needs a path")
        path = document["path"]
        if path in seen:
            raise SystemExit(f"duplicate documentation path: {path}")
        seen.add(path)
        relative = path.removeprefix("docs/")
        if not (ROOT / path).is_file():
            raise SystemExit(f"indexed document is missing: {path}")
        if f"]({relative})" not in human:
            raise SystemExit(f"human index does not link {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
