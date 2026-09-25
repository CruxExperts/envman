---
layout: default
title: Encrypted backups and migration
---

# Encrypted backups and migration

Envman writes portable encrypted backups as authenticated JSON envelopes. When `ENVMAN_BACKUP_KEY` is explicitly configured, Envman uses that value. If it is unset, Envman may use a generated private fallback at `$XDG_CONFIG_HOME/envman/encryption.key` when `XDG_CONFIG_HOME` is set, or `$HOME/.config/envman/encryption.key` otherwise, with mode `0600`. This export credential is separate from the automatically generated storage key and the encrypted `environment.conf` file.

Envman never creates or replaces the fallback key silently. At TUI startup, Envman clearly prompts before generating a missing key; declining leaves state unchanged and encrypted-backup operations unavailable. Existing key files are preserved, and malformed key files fail closed.

The automation/AI-agent path is explicit:

```bash
envman key --generate --approve-key-generation
```

`--yes` and `--force` are not approval. Key-generation output never prints key material. For an explicitly configured environment key, use a password manager or another trusted mechanism that does not record the value in shell history:

```bash
export ENVMAN_BACKUP_KEY="$(password-manager read envman-backup-key)"
```

Envman derives a Fernet key from the selected key text with Scrypt and never writes the password into the backup. The envelope records the schema, Envman version, creation time, encryption parameters, and ciphertext, not plaintext variable names or values. Backup parent directories use mode `0700`, backup files mode `0600`, and symlinked destinations or parent directories are refused.

## Export and import

The CLI `export` command always includes every managed variable. Its optional destination can be a file or an existing directory. Without a destination, Envman writes `envman-YYYYMMDDTHHMMSSZ.json` in the current directory. The TUI **B** action exports the selected variables, or all managed variables when the selection is empty. Both interfaces require an approved key; after a declined TUI prompt, encrypted-backup operations remain unavailable.

The CLI `import-backup` command and TUI **J** preview the decrypted candidates before changing storage. Preview does not persist anything. To apply a subset, name the variables; to apply all candidates, use `--all`; in either case, add `--apply`. A selected name that collides with a managed variable requires `--replace`. `--force` and `--yes` only suppress advisory warnings; they do not approve key generation or bypass validation, authentication, or collision protection.

An import rejects a missing or incorrect key, a malformed or oversized JSON envelope, unsupported encryption metadata, unauthenticated ciphertext, duplicate names, invalid names or values, and unsafe `PATH` or URL values. Secret recognition and the six-character minimum are the same as for normal edits; see [storage and shell loading](../reference/storage-and-shell-loading.md).

## Migration procedure

To convert an older local plaintext store and its automatic environment snapshots in place, first retain a recoverable encrypted export, then preview and apply:

```bash
envman export ./envman-recovery.json
envman migrate-storage
envman migrate-storage --apply
envman check
```

The conversion verifies each replacement archive, preserves its filename, and does not touch profile snapshots. It cannot erase external backups, filesystem snapshots, or SSD remnants. Keep the storage key separate from copies of the encrypted configuration. The portable export uses its own backup credential, which you need to restore onto another machine.

For migration between machines:

1. On the source machine, configure `ENVMAN_BACKUP_KEY` without placing it in a file or command history, or use the approved fallback key, then run `envman export` or use **B** in the TUI.
2. Transfer the encrypted JSON through a channel appropriate for sensitive data. The file is encrypted, but the key still needs separate protection.
3. On the destination machine, configure the same environment key or provision the fallback key, then preview with `envman import-backup path/to/backup.json` or TUI **J**.
4. Select explicit names or all candidates, then apply with `--apply` (and `--replace` only when an intentional collision replacement is required).

For process-environment imports, copy and rename rules, see [the CLI reference](cli.md). For the file and shell-loader locations that are preserved during migration, see [storage and shell loading](../reference/storage-and-shell-loading.md).
