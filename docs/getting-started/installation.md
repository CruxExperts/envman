---
layout: default
title: Install Envman
---

# Install Envman

Envman 0.1.5 supports Linux x86_64, CPython `>=3.12,<3.13`, and `uv >=0.11,<0.12`; use `uv 0.11.21` for this release. Run the public installer through `uv`; do not pipe the downloaded file to a shell.

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py
ENVMAN="$(uv tool dir --bin)/envman"
"$ENVMAN" --version
"$ENVMAN"
```

The installer downloads the bounded release manifest, accepts only the trusted `CruxExperts/envman` GitHub release asset URLs, checks asset sizes and SHA-256 hashes, validates the pinned runtime constraints and wheel metadata, checks the host and `uv` versions, and installs only the verified local wheel with `uv tool install --no-build`. It resolves the installed executable from `uv tool dir --bin`, so verification does not depend on the tool directory already being present in `PATH`. If an Envman tool is already present, replacement requires a valid Envman install receipt.

The resolved executable command works before the uv tool directory is in `PATH`. After adding the directory reported by `uv tool dir --bin` to `PATH`, use the shorter `envman` command.

## Update

```bash
envman update --check
envman update --check --json
envman update
```

After installation, Envman writes an atomic mode-`0600` receipt at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. The receipt records the installed version, provider, repository, manifest URL, verified wheel and constraints assets, installer and `uv` versions; receipts created by the 0.1.5 installer record `installer_version: 0.1.5`. Updates use only the recorded provider and manifest source.

`update --check` reports `current` or `update-available` without changing the tool. `update` refuses a downgrade and does not reinstall the same version. It verifies the candidate assets before installation and keeps the previous verified wheel, constraints, and receipt available for rollback if replacement fails. A missing, malformed, symlinked, or untrusted receipt is a trust error; Envman does not silently switch update channels.

See [installation sources and updates](../reference/install-source-and-updates.md) for the trust boundary, receipt schema, rollback behavior, and uninstall notes. The installed tool's managed values and shell loaders are separate; see [storage and shell loading](../reference/storage-and-shell-loading.md).
