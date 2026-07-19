---
layout: default
title: Architecture
---

# Architecture

`src/envman/cli.py` owns the terminal UI, CLI parser, persistent environment store, validation rules, shell loader handling, and encrypted backup flow. `src/envman/_release_protocol.py` is deliberately stdlib-only: it owns manifest and receipt schema validation, secure transport checks, wheel inspection, and uv-tool replacement semantics.

`install.py` is generated from `_release_protocol.py` by `scripts/render_installer.py`; edit the canonical protocol, not the generated installer. `VERSION` is the sole version source, projected into package metadata through Hatchling.

The package deliberately has no web framework, Node toolchain, linter dependency, or test framework dependency. Standard-library `unittest` protects observable behavior.
