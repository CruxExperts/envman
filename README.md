# Envman
**Version:** 0.1.2

Envman manages durable, per-user environment variables on Linux. Use the terminal UI to inspect and edit them, or the CLI to validate and automate changes without putting values in shell startup files by hand.

- Linux x86_64 releases for CPython 3.12 and `uv >=0.11,<0.12`
- A verified GitHub-release installer and receipt-directed updates
- A curses TUI and a scriptable CLI with JSON output
- Encrypted backup export and selective import

## Install

The release installer checks the GitHub manifest, immutable asset URLs, sizes, SHA-256 hashes, wheel metadata, runtime constraints, and the local runtime before it installs the wheel.

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py
```

The installer currently accepts Linux x86_64, CPython `>=3.12,<3.13`, and `uv >=0.11,<0.12`. It does not silently change installation providers when an installation receipt is missing or invalid.

## First run

```bash
envman
```

With no command, Envman opens the TUI. A new store starts empty; press `A` to add a variable. The catalog uses the available terminal height and requires at least 80 columns by 18 rows. Press `Q` or `Esc` to leave the catalog and start a child shell with the managed environment.

The CLI is available when an interactive terminal is not appropriate:

```bash
envman set PROJECT_URL --value https://example.test
envman list --json
```

## TUI controls

- `Up`/`Down` moves focus. `Space` toggles the focused variable, so several variables can be selected.
- `C` copies one source value into every selected variable; with no selection it targets the focused variable.
- `D` deletes the selected variables; with no selection it targets the focused variable.
- `B` writes an encrypted backup of the selected variables, or all managed variables when nothing is selected.
- `A` adds, `E` or `Enter` edits, and `R` renames the focused variable.
- `O` changes ordering, `F` sets a filter, `M` changes filter scope, and `[`/`]` scrolls details.
- `I` previews process-environment imports. `J` previews an encrypted-backup import.

Use `envman --nocolor` when the terminal cannot use curses color pairs. The [TUI guide](docs/guides/tui.md) has the complete control reference.

## Values and masking

Names in the `KEY` class and names containing terms such as `TOKEN`, `PASSWORD`, `SECRET`, `CREDENTIAL`, or `PRIVATE_KEY` are treated as sensitive. Names ending in `_API_KEY_ENV` are references to managed variables, not secrets themselves. URLs that contain a password are also sensitive.

Sensitive values are masked in normal TUI and CLI output. Values of six to nine characters show one character at each edge, values of 10 to 15 show two, and values of 16 or more show four. Sensitive values shorter than six characters are rejected. `--reveal` is an explicit request to print a sensitive value and should be used only by a trusted caller.

## What Envman changes

Envman stores assignments in `${XDG_CONFIG_HOME:-$HOME/.config}/envman/environment.conf` with private permissions. Saving also installs small, marked loaders for supported POSIX shells and Fish. Existing shell profile text is preserved, and comments or blank lines in the managed file remain in place. When an earlier file exists, writes create timestamped mode-`0600` local snapshots under the Envman backup directory.

The configuration file is not an encrypted secret store. Protect the configuration directory and the process environment that loads it. Encrypted export is separate:

```bash
envman export backup.json
envman import-backup backup.json --all --apply
```

Set `ENVMAN_BACKUP_KEY` through a secure mechanism before export or import. Do not put that password, a backup file, or managed values in source control.

## Updates and removal

Updates follow the provider recorded in the installation receipt:

```bash
envman update --check
envman update
```

An update refuses a downgrade. If a verified update fails, Envman restores the previous wheel and receipt. `uv tool uninstall envman` removes the installed command; the managed configuration, local backups, and shell loader files are separate and remain until you remove them. See [installation sources and updates](docs/reference/install-source-and-updates.md) for receipt recovery and intentional rollback.

## Documentation and support

- [Installation](docs/getting-started/installation.md)
- [CLI reference](docs/guides/cli.md)
- [TUI guide](docs/guides/tui.md)
- [Backups and migration](docs/guides/backups-and-migration.md)
- [Storage and shell loading](docs/reference/storage-and-shell-loading.md)
- [Architecture](docs/development/architecture.md)
- [Versioning and releases](docs/development/versioning-and-releases.md)

Ask questions in [GitHub Discussions](https://github.com/CruxExperts/envman/discussions), report reproducible defects in [GitHub Issues](https://github.com/CruxExperts/envman/issues), and see [SUPPORT.md](SUPPORT.md) for sanitized diagnostics. Report suspected vulnerabilities through [private vulnerability reporting](https://github.com/CruxExperts/envman/security/advisories/new), not a public issue. Contributors should read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Envman is released under the [MIT License](LICENSE).
