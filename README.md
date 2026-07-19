# Envman

**Version:** 0.1.1

Envman is a portable terminal environment-variable manager for Linux. One variable is easy; dozens of credentials, URLs, paths, and settings across shells and machines become hard to find, validate, and move without leaks. Envman keeps the managed set durable, visible, and portable.

- Terminal UI for browsing, filtering, editing, importing, and validating variables.
- Scriptable CLI with structured JSON output and safe masking by default.
- Authenticated encrypted backup/import envelopes for machine-to-machine migration.
- Release installer that verifies a GitHub manifest, hashes, wheel metadata, compatibility, and pinned runtime constraints before installation.

## Install

Requires Linux x86_64, CPython 3.12, and `uv >=0.11,<0.12`.

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py
envman
```

Check or apply a verified update after installation:

```bash
envman update --check
envman update
```

## Quick use

```bash
envman set PROJECT_URL --value https://example.test
envman list --json
envman export backup.json
envman import-backup backup.json --all --apply
```

`ENVMAN_BACKUP_KEY` supplies the encrypted-backup password. Do not place it in the managed Envman file or commit it to source control.

## Documentation

- [Install, trust boundaries, and updates](docs/getting-started/installation.md)
- [Terminal UI guide](docs/guides/tui.md)
- [CLI reference](docs/guides/cli.md)
- [Encrypted backups and migration](docs/guides/backups-and-migration.md)
- [Storage and shell loading](docs/reference/storage-and-shell-loading.md)
- [Architecture](docs/development/architecture.md)
- [Versioning and releases](docs/development/versioning-and-releases.md)

The public site is [cruxexperts.github.io/envman](https://cruxexperts.github.io/envman/).

## Security boundary

Envman masks sensitive values in normal UI and CLI output, but it cannot protect values deliberately revealed to another process or terminal. Release installation trusts the locally installed `uv`, its selected Python runtime, GitHub release hosting, and PyPI for exact wheels resolved under verified runtime constraints. See [SECURITY.md](SECURITY.md).

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md), open questions in [GitHub Discussions](https://github.com/CruxExperts/envman/discussions), and report security issues through [private vulnerability reporting](https://github.com/CruxExperts/envman/security/advisories/new).

Copyright (c) 2026 CruxExperts contributors. Released under the [MIT License](LICENSE).
