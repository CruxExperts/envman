# Product

## Purpose

Envman manages durable, per-user environment variables without requiring users to edit shell startup files by hand. The terminal UI makes the managed set inspectable. The CLI supports validation, JSON output, imports, exports, and automation.

## Users

Envman is for developers and operators who work across shells or machines and need a small, explicit set of URLs, paths, settings, and credentials. It is not a general-purpose secret vault or a replacement for a shell, operating-system credential store, or deployment secret manager.

## Supported scope

Release installation currently supports Linux x86_64, CPython `>=3.12,<3.13`, and `uv >=0.11`. The managed store is per user. A save writes the Envman configuration file and maintains marked loaders for supported POSIX shells and Fish; when replacing an existing file, Envman creates a local mode-`0600` snapshot.

Sensitive names and password-bearing URLs are masked in ordinary output. When explicitly configured, encrypted backups use `ENVMAN_BACKUP_KEY`. If it is unset, Envman may use a generated private fallback at `${XDG_CONFIG_HOME:-$HOME/.config}/envman/encryption.key` (mode `0600`); the fallback is separate from the unencrypted on-disk configuration and automatic local snapshots.

## Product principles

- Show the current state before asking for an action.
- Make every interactive operation available through a scriptable command where it is useful.
- Keep selection, validation, masking, and persistence behavior explicit.
- Require explicit approval before generating a fallback key; preserve existing keys and fail closed on malformed key files.
- Separate masking, file permissions, encrypted export, and installer verification; none is a promise of complete secrecy.
- Prefer a quiet terminal surface that remains usable without color.

The TUI asks before generating a missing fallback key at startup. Declining leaves state unchanged and encrypted-backup operations unavailable. Automation and AI agents must use `envman key --generate --approve-key-generation`; `--yes` and `--force` are not approval, and key material is never printed.

## Out of scope

Envman does not provide hosted synchronization, team access control, key rotation, remote secret storage, or a hermetic dependency installation. The installer itself must not silently generate an encrypted-backup key; users remain responsible for the local shell, `uv`, Python runtime, release hosting, dependency indexes, and operating-system permissions.
