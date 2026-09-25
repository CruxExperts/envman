---
layout: default
title: Install Envman
---

# Install Envman

Envman 0.1.9 supports Linux x86_64, CPython `>=3.12,<3.13`, and `uv >=0.11`. The installer is a single command that works on Ubuntu servers with Python 3.12 and uv already installed:

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py
```

The command checks the bounded release manifest, immutable asset URLs, sizes, SHA-256 hashes, wheel metadata, runtime constraints, the Linux host, Python runtime, and the local uv minimum before installing the verified wheel with `uv tool install --no-build`. It resolves the installed executable from `uv tool dir --bin`, so verification does not depend on that directory already being in `PATH`. After adding that directory to `PATH`, invoke the command as `envman`.


## Encrypted-backup key setup

When `ENVMAN_BACKUP_KEY` is explicitly configured, encrypted backups use it. Otherwise the first runtime may offer a private mode-`0600` fallback at `${XDG_CONFIG_HOME:-$HOME/.config}/envman/encryption.key`. The TUI clearly prompts before generating a missing key; declining leaves state unchanged and encrypted-backup operations unavailable.

For automation or AI agents, use `envman key --generate --approve-key-generation`. `--yes` and `--force` are not approval. The command never prints key material, preserves an existing key file, and fails closed for malformed key files.

## Optional agent skill

Releases that include the optional agent skill accept these installer flags:

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py --install-skill
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py --no-install-skill
```

With neither flag, the installer prompts only when stdin and stdout are TTYs. An empty interactive answer defaults to **Yes**. Non-TTY execution never blocks and defaults to **No**, unless `--install-skill` explicitly forces installation.

When enabled, the installer verifies the manifest's skill asset and installs it only within the selected repository. It walks upward from the current directory to the nearest `.git` directory; if none exists, it uses the current directory. It installs the same verified asset into each detected existing supported repo-local root: `.agents/skills`, `.codex/skills`, `.claude/skills`, `.cursor/skills`, `.gemini/skills`, and `.opencode/skills`; if no supported root exists, it creates `.agents/skills`. Within each root, the destination is `envman-environment-variable-manager/SKILL.md`. Symlinks and paths escaping the selected repository are rejected, and an unmarked existing skill is never replaced.

The immutable `v0.1.5` release predates this optional skill asset. Envman 0.1.6 is the first release containing it.

## Update

```bash
envman update --check
envman update --check --json
envman update
```

After installation, Envman writes an atomic mode-`0600` receipt at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. The receipt records the installed version, provider, repository, manifest URL, verified wheel and `uv` versions; receipts created by the 0.1.9 installer record `installer_version: 0.1.9`. Updates use only the recorded provider and manifest source.

`update --check` reports `current` or `update-available` without changing the tool. `update` refuses a downgrade and does not reinstall the same version. It verifies the candidate assets before installation and keeps the previous verified wheel, constraints, and receipt available for rollback if replacement fails. A missing, malformed, symlinked, or untrusted receipt is a trust error; Envman does not silently switch update channels.

See [installation sources and updates](../reference/install-source-and-updates.md) for the trust boundary, receipt schema, rollback behavior, and uninstall notes. The installed tool's managed values and shell loaders are separate; see [storage and shell loading](../reference/storage-and-shell-loading.md).
