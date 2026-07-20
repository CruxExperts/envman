# Product

## Purpose

Envman manages durable, per-user environment variables without requiring users to edit shell startup files by hand. The terminal UI makes the managed set inspectable. The CLI supports validation, JSON output, imports, exports, and automation.

## Users

Envman is for developers and operators who work across shells or machines and need a small, explicit set of URLs, paths, settings, and credentials. It is not a general-purpose secret vault or a replacement for a shell, operating-system credential store, or deployment secret manager.

## Supported scope

Release installation currently supports Linux x86_64, CPython `>=3.12,<3.13`, and `uv >=0.11,<0.12`. The managed store is per user. A save writes the Envman configuration file and maintains marked loaders for supported POSIX shells and Fish; when replacing an existing file, Envman creates a local mode-`0600` snapshot.

Sensitive names and password-bearing URLs are masked in ordinary output. Names ending in `_API_KEY_ENV` refer to another managed variable. Encrypted backups use `ENVMAN_BACKUP_KEY`; the on-disk configuration and automatic local snapshots are not encrypted.

## Product principles

- Show the current state before asking for an action.
- Make every interactive operation available through a scriptable command where it is useful.
- Keep selection, validation, masking, and persistence behavior explicit.
- Separate masking, file permissions, encrypted export, and installer verification; none is a promise of complete secrecy.
- Prefer a quiet terminal surface that remains usable without color.

## Out of scope

Envman does not provide hosted synchronization, team access control, key rotation, remote secret storage, or a hermetic dependency installation. Users remain responsible for the local shell, `uv`, Python runtime, release hosting, dependency indexes, and operating-system permissions.
