---
layout: default
title: Testing
---

# Testing

## Locked development environment

The project targets CPython 3.12 and pins the development toolchain through `pyproject.toml` and `uv.lock` (`uv 0.11.21`). Start from a clean checkout with:

```bash
uv sync --locked --group dev
```

The release workflow's authoritative test command discovers the `unittest.TestCase` classes below `tests/`:

```bash
uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'
```

Do not replace `--locked --no-sync` with an unconstrained environment when checking a release. The discovery command covers storage and shell-loader preservation, input validation and masking, TUI recovery and selection behavior, import and encrypted-backup round trips, version lookup, and release-protocol trust boundaries. Release-protocol tests inject transport, state roots, and command runners; they do not contact production GitHub or mutate a developer's real uv tools.

## Focused source checks

Use these local source-integrity checks before opening a release tag. The release workflow runs the version, documentation, and installer-parity checks from this list after its locked test command:

```bash
uv run --locked --no-sync python -m py_compile src/envman/*.py scripts/*.py install.py
uv run --locked --no-sync python scripts/version.py check
uv run --locked --no-sync python scripts/check_docs.py
uv run --locked --no-sync python scripts/render_installer.py
git diff --exit-code -- install.py
```

`check_docs.py` treats `docs/index.yaml` as the machine source of truth and requires every indexed file to exist and be linked from `docs/INDEX.md`. Rendering must leave the committed installer unchanged; edit `_release_protocol.py`, not `install.py`, when the protocol changes.

## Reproducible release checks

Before publishing, build the artifacts twice from the tagged commit timestamp and compare both outputs:

```bash
export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
uv build --no-build-isolation --out-dir /tmp/release-a
uv build --no-build-isolation --out-dir /tmp/release-b
cmp /tmp/release-a/envman-*.whl /tmp/release-b/envman-*.whl
cmp /tmp/release-a/envman-*.tar.gz /tmp/release-b/envman-*.tar.gz
```

The release job then runs `scripts/release_assets.py` to generate exact runtime constraints, the manifest, and `SHA256SUMS.txt`. Verify the isolated wheel installation and the private install receipt before treating the release as ready.
