---
layout: default
title: Install Envman
---

# Install Envman

Envman 0.1.10 supports Linux x86_64, CPython `>=3.12,<3.13`, and `uv >=0.11`. The installer is a single command that works on Ubuntu servers with Python 3.12 and uv already installed:

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py
```

The command checks the bounded release manifest, immutable asset URLs, sizes, SHA-256 hashes, wheel metadata, runtime constraints, the Linux host, Python runtime, and the local uv minimum before installing the verified wheel with `uv tool install --no-build`. It resolves the installed executable from `uv tool dir --bin`, so verification does not depend on that directory already being in `PATH`. After adding that directory to `PATH`, invoke the command as `envman`.


## Encrypted-backup key setup

When `ENVMAN_BACKUP_KEY` is explicitly configured, encrypted backups use it. Otherwise the first runtime may offer a private mode-`0600` fallback at `${XDG_CONFIG_HOME:-$HOME/.config}/envman/encryption.key`. The TUI clearly prompts before generating a missing key; declining leaves state unchanged and encrypted-backup operations unavailable.

For automation or AI agents, use `envman key --generate --approve-key-generation`. `--yes` and `--force` are not approval. The command never prints key material, preserves an existing key file, and fails closed for malformed key files.

## Optional agent skill

Releases that include the optional agent skill accept explicit scope and agent targeting:

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py --install-skill
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py --install-skill --skill-scope global
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py --install-skill --skill-scope repository --skill-target opencode
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py --install-skill --skill-target all
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py --no-install-skill
```

With neither install flag, the installer prompts only when stdin and stdout are TTYs. An empty interactive answer defaults to **Yes**. Non-TTY execution never blocks and defaults to **No**. Supplying `--skill-scope` or `--skill-target` implies `--install-skill`; those options cannot be combined with `--no-install-skill`.

`--skill-scope auto` is the default. It selects the nearest Git repository when one exists and otherwise selects the current user's home directory. `repository` requires a directory inside a Git repository. `global` uses the home directory as a strict path boundary.

Envman is pinned to LocalSetup 5.6.2 for its supported agent catalog and placement rules. The accepted `--skill-target` values are `amp-cli`, `antigravity-app`, `claude-code`, `cline-cli`, `cline-vscode`, `codex`, `cursor`, `factory-droid`, `gemini-cli`, `github-copilot-cli`, `github-copilot-vscode`, `goose-cli`, `hermes-agent`, `kilo`, `kimi-cli`, `omp-cli`, `openclaw`, `opencode`, `pi-cli`, and `qwen-code-cli`, plus `auto` and `all`.

Canonical destinations follow LocalSetup's generated write-path projection:

| Agent target | Repository root | Global root |
| --- | --- | --- |
| `claude-code` | `.claude/skills` | `~/.claude/skills` |
| `cline-cli`, `cline-vscode` | `.cline/skills` | `~/.cline/skills` |
| `hermes-agent` | `.hermes/skills` | `~/.hermes/skills` |
| `antigravity-app` | `.agents/skills` | `~/.gemini/config/skills` |
| All other targets | `.agents/skills` | `~/.agents/skills` |

Automatic discovery also recognizes LocalSetup's existing native and historical directory shapes. These include `.codex/skills`, `.cursor/skills`, `.gemini/skills`, `.kilo/skill`, `.kilo/skills`, `.kilocode/skill`, `.kilocode/skills`, `.openclaw/skills`, `.opencode/skill`, `.opencode/skills`, `.agent/skills`, `.omp/skills`, and the equivalent supported global paths. An explicit target always includes its canonical write root and refreshes any of that target's recognized roots that already exist. `all` creates each unique canonical write root and refreshes every recognized root already present.

Within each root, the destination is `envman-environment-variable-manager/SKILL.md`. The release manifest and skill lock must match. Symlinks and paths escaping the selected scope are rejected, and an unmarked existing skill is never replaced. Multi-root installation is atomic from Envman's perspective: a failed write restores the prior marked skill files and removes newly created empty paths when safe.

The immutable `v0.1.5` release predates this optional skill asset. Envman 0.1.6 is the first release containing it.

## Update

```bash
envman update --check
envman update --check --json
envman update
envman update --install-skill --skill-scope global --skill-target codex
envman update --install-skill --skill-scope repository --skill-target opencode
```

After installation, Envman writes an atomic mode-`0600` receipt at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. The receipt records the installed version, provider, repository, manifest URL, verified wheel and `uv` versions; receipts created by the 0.1.10 installer record `installer_version: 0.1.10`. Updates use only the recorded provider and manifest source.

`update --check` reports `current` or `update-available` without changing the tool. `update` refuses a downgrade and does not reinstall the same tool version. With `--install-skill`, it downloads the skill from the latest verified GitHub release and installs or refreshes it even when the tool is already current. Scope or target options imply `--install-skill`; `--check` cannot be combined with skill installation. A tool update verifies candidate assets and keeps the previous verified wheel, constraints, skill files, and receipt available for rollback if replacement fails. A missing, malformed, symlinked, or untrusted receipt is a trust error; Envman does not silently switch update channels.

See [installation sources and updates](../reference/install-source-and-updates.md) for the trust boundary, receipt schema, rollback behavior, and uninstall notes. The installed tool's managed values and shell loaders are separate; see [storage and shell loading](../reference/storage-and-shell-loading.md).
