---
layout: default
title: Install Envman
---

# Install Envman

Envman 0.1.1 supports Linux x86_64 with CPython 3.12 and `uv >=0.11,<0.12`.

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py
envman --version
envman
```

The installer verifies the release manifest, wheel and constraints hashes, wheel metadata, platform compatibility, and `uv` version before installing an Envman wheel with `uv tool install --no-build`. It refuses to replace an existing Envman tool without a valid Envman installation receipt.

## Update

```bash
envman update --check
envman update
```

Updates use only the provider recorded in `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. A missing, malformed, symlinked, or unrecognized receipt is a trust error, not a request to silently switch update channels.

See [installation sources and updates](../reference/install-source-and-updates.md) for trust boundaries and recovery.
