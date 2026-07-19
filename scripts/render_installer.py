#!/usr/bin/env python3
"""Render the committed standalone installer from Envman's canonical protocol."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "src" / "envman" / "_release_protocol.py"
OUTPUT = ROOT / "install.py"
HEADER = '''#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///
# GENERATED FILE: edit src/envman/_release_protocol.py and rerun this renderer.
# This installer intentionally carries the canonical stdlib-only release protocol.

'''
ENTRYPOINT = '''\n\nif __name__ == "__main__":\n    raise SystemExit(installer_main())\n'''


def render() -> str:
    return HEADER + PROTOCOL.read_text(encoding="utf-8") + ENTRYPOINT


def main() -> None:
    OUTPUT.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
