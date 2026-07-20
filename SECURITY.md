# Security policy

## Report a vulnerability

Report suspected vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/CruxExperts/envman/security/advisories/new). Do not open a public issue for a vulnerability. Do not include secrets, managed values, backup passwords, or unredacted installation receipts in a report.

Include a concise description, affected Envman version or release asset, reproduction steps, impact, and sanitized logs. A maintainer may ask for additional evidence or coordinate disclosure after the issue is understood.

## Scope

This policy covers Envman's source, release installer, published release assets, and repository automation. It does not make the local `uv` executable, Python runtime, shell configuration, GitHub account, PyPI, or the rest of the machine part of Envman's security boundary.

Envman masks sensitive values in ordinary TUI and CLI output, but a caller that requests `--reveal`, reads the managed file, or receives the process environment can still obtain them. The managed configuration and automatic local snapshots are not encrypted. Encrypted backup files are protected by `ENVMAN_BACKUP_KEY`; protect that password and the backup file separately.

## Installation trust

The verified installer checks release-manifest structure, GitHub asset URLs, sizes, SHA-256 hashes, wheel metadata, runtime constraints, and compatibility before installation. It still trusts the local `uv` executable and Python runtime, GitHub release hosting, and the dependency index used for exact runtime wheels. See [installation sources and updates](docs/reference/install-source-and-updates.md).
