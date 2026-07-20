---
layout: default
title: Architecture
---

# Architecture

## Application boundary

Envman's runtime is a small Python 3.12 package. `src/envman/cli.py` owns the command-line parser, terminal UI, persistent environment store, validation and masking rules, shell-loader installation, import flows, and encrypted backups. `src/envman/_release_protocol.py` is intentionally standard-library-only because the committed `install.py` is generated from it and runs with `uv run --script`.

The project has no web framework, Node toolchain, linter dependency, or test-framework dependency in its runtime. Hatchling reads the single `VERSION` file for package metadata. The CLI reads installed distribution metadata and falls back to that source-checkout file when the package is not installed.

The small scripts have separate boundaries:

- `scripts/version.py` plans and checks the patch-default Conventional Commit release policy.
- `scripts/render_installer.py` renders `install.py` from `_release_protocol.py`.
- `scripts/release_assets.py` creates the pinned runtime-constraints projection, release manifest, and SHA-256 list.
- `scripts/check_docs.py` checks that every machine-index path exists and is linked by `docs/INDEX.md`.

## Managed state

`XDG_CONFIG_HOME` must be an absolute path when set. Otherwise Envman uses `$HOME/.config`. The managed file is `envman/environment.conf`; writes use a temporary file, mode `0600`, and a timestamped `0600` tar.gz snapshot under `envman/backups/` before replacement. The utility directory is created with mode `0700` and symlinked targets are rejected.

`envman init` installs loaders without adding a variable. The POSIX loader is `load-env.sh`; Envman adds guarded loader blocks to the supported profile files and writes a Fish loader at `fish/conf.d/envman.fish`. Existing profile content is preserved, and each profile is backed up before a loader block is added.

## Terminal UI and CLI

The TUI requires at least 80 columns by 18 rows. Its catalog capacity is computed from the current terminal height, so the catalog and detail view use the full available area instead of a fixed page index. Arrow keys move the current row, `[` and `]` scroll detail text, and Space toggles a variable in the multi-selection. `C` copies one source value to the selected targets, `D` deletes the selected group after confirmation, and `B` exports the selected group as an encrypted backup. Every prompt clears the prompt row before drawing its next frame.

The CLI exposes `init`, `target`, `check`, `update`, `list`, `get`, `import`, `export`, `import-backup`, `set`, `unset`, `rename`, and `validate`. Commands accept `--json` for stable machine-readable output. Sensitive values stay masked unless a caller explicitly supplies `--reveal`; `--force` and `--yes` suppress advisory warnings only.

Sensitivity is name- and value-aware. `KEY`-class names are sensitive, except names ending in `_API_KEY_ENV`, which are references to another managed variable. Sensitive values shorter than six characters are rejected. Masks show 1+1 characters for lengths 6-9, 2+2 for 10-15, and 4+4 for lengths of at least 16. URLs containing a password are also treated as sensitive.

Encrypted backups use the `ENVMAN_BACKUP_KEY` environment variable and an authenticated Fernet envelope with an scrypt-derived key. The JSON envelope contains the schema, version, creation time, KDF parameters, and ciphertext. Import validates the envelope and previews selected changes before applying them.

## Release protocol

The generated installer and the `update` command share `_release_protocol.py`. They accept only the exact release-manifest schema for `CruxExperts/envman`, Linux x86_64, Python `>=3.12,<3.13`, and `uv >=0.11,<0.12`. Manifest assets must use immutable GitHub release URLs and declare bounded sizes and lowercase SHA-256 hashes. Downloads accept only GitHub-controlled HTTPS redirects; the wheel's Envman name and version, and every runtime constraint pin, are checked before installation.

Installation uses `uv tool install --no-build` and writes a private receipt at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. The receipt records the installed version, provider, manifest URL, asset metadata, installer version, `uv` version, and timestamp. Replacing an existing Envman tool requires a valid Envman receipt; updates use the recorded provider and refuse a downgrade. A failed replacement attempts to restore the previous wheel and receipt.

## Deterministic release assets

`install.py` must be rendered from the canonical protocol and committed without a diff:

```bash
uv run --locked --no-sync python scripts/render_installer.py
git diff --exit-code -- install.py
```

The tag-gated GitHub release workflow sets `SOURCE_DATE_EPOCH` to the tagged commit timestamp, builds twice with `uv build --no-build-isolation`, and compares the wheel and source archive byte-for-byte. `scripts/release_assets.py` then writes exact runtime pins from `uv.lock`, `release-manifest.json`, and `SHA256SUMS.txt`. The publish job creates a draft release from the matching changelog section, attests every release asset, and makes the release public only after those steps succeed.
