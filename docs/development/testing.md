---
layout: default
title: Testing
---

# Testing

Run the complete suite in the locked development environment:

```bash
uv sync --locked --group dev
uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'
uv run --locked --no-sync python -m py_compile src/envman/*.py scripts/*.py install.py
```

Tests cover persistent storage, shell-loader preservation, TUI recovery behavior, CLI validation and masking, encrypted backup round trips, package version lookup, and release protocol trust boundaries. Release protocol tests inject transport, state roots, and command runners; they must never contact production GitHub or alter a developer's real uv tools.

Before release, render `install.py` again and require no diff, build twice with a fixed `SOURCE_DATE_EPOCH`, compare artifacts, and install the wheel into temporary uv-tool roots.
