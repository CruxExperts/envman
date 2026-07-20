---
layout: default
title: Encrypted backups and migration
---

# Encrypted backups and migration

Envman writes encrypted backups as authenticated JSON envelopes. Set `ENVMAN_BACKUP_KEY` in the process environment for every export and import; Envman derives a Fernet key from that text with Scrypt and never writes the password into the backup. The envelope records the schema, Envman version, creation time, encryption parameters, and ciphertext, not plaintext variable names or values.

Populate `ENVMAN_BACKUP_KEY` through a password manager or another trusted mechanism that does not record the value in shell history. Then run:

```bash
envman export ./envman-backup.json
envman import-backup ./envman-backup.json --all --apply
```

The key derivation uses a random 16-byte salt, Scrypt `N=131072`, `r=8`, `p=1`, and a 32-byte derived key. Fernet authenticates the ciphertext. Envman creates a missing backup parent directory with mode `0700` and writes backup files with mode `0600`; it refuses symlinked destinations and symlinked parent directories.

## Export and import

The CLI `export` command always includes every managed variable. Its optional destination can be a file or an existing directory. Without a destination, Envman writes `envman-YYYYMMDDTHHMMSSZ.json` in the current directory. The TUI **B** action exports the selected variables, or all managed variables when the selection is empty.

The CLI `import-backup` command and TUI **J** preview the decrypted candidates before changing storage. Preview does not persist anything. To apply a subset, name the variables; to apply all candidates, use `--all`; in either case, add `--apply`. A selected name that collides with a managed variable requires `--replace`. `--force` and `--yes` only suppress advisory warnings; they do not bypass validation, authentication, or collision protection.

An import rejects a missing or incorrect `ENVMAN_BACKUP_KEY`, malformed or oversized JSON, unsupported encryption metadata, unauthenticated ciphertext, duplicate names, invalid names or values, and unsafe `PATH` or URL values. Secret recognition and the six-character minimum are the same as for normal edits; see [storage and shell loading](../reference/storage-and-shell-loading.md).

## Migration procedure

1. On the source machine, set `ENVMAN_BACKUP_KEY` without placing it in a file or command history, then run `envman export` or use **B** in the TUI.
2. Transfer the encrypted JSON through a channel appropriate for sensitive data. The file is encrypted, but the key still needs separate protection.
3. On the destination machine, set the same key and preview with `envman import-backup path/to/backup.json` or TUI **J**.
4. Select explicit names or all candidates, then apply with `--apply` (and `--replace` only when an intentional collision replacement is required).

For process-environment imports, copy and rename rules, see [the CLI reference](cli.md). For the file and shell-loader locations that are preserved during migration, see [storage and shell loading](../reference/storage-and-shell-loading.md).
