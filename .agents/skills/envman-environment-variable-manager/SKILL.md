---
name: envman-environment-variable-manager
description: Manage Envman CLI and terminal UI workflows for durable environment variables, process or encrypted-backup imports, shell loaders, encrypted backups, verified GitHub installation or updates, and receipt behavior. Use for Envman commands, TUI controls, managed-variable safety, migration, or release updates; do not use for generic shell questions unrelated to Envman.
---

<!-- envman-skill-lock: version=0.1.6 source=src/envman/cli.py -->

# Envman

Use Envman to maintain validated, per-user environment variables without hand-editing
shell startup files. Prefer the CLI for automation and JSON output; use the curses
TUI for interactive inspection and editing.

## Safety invariants

- Treat the managed configuration and process environment as sensitive. They are not
  an encrypted secret store; protect their directories and permissions.
- Keep sensitive values masked. Request `--reveal` only for a secure, intentional
  caller, and never paste values into logs, source control, or prompts.
- Preview imports before applying. `--apply` is required to persist changes;
  `--replace` is required for intentional managed-name collisions. `--force` and
  `--yes` suppress advisory warnings only and never bypass validation.
- Set `ENVMAN_BACKUP_KEY` through a password manager or another trusted mechanism.
  Keep it, plaintext values, and backup files out of shell history and source
  control. Transfer the encrypted backup and its key through separate channels.
- Updates must remain receipt-directed and verified against the immutable GitHub
  release protocol. Do not bypass manifest, hash, compatibility, or downgrade
  checks.

## CLI

Initialize shell loaders, inspect state, and validate values:

```bash
envman init
envman target --json
envman check --json
envman set PROJECT_URL --value 'https://example.test'
envman get PROJECT_URL
envman list --json
envman validate API_TOKEN --stdin
```

For process-environment migration, preview first and select names explicitly (or
use `--all`), then apply:

```bash
API_TOKEN='value supplied by a secure process' envman import API_TOKEN
envman import --all
API_TOKEN='value supplied by a secure process' envman import API_TOKEN --apply
envman import --all --apply
```

<!-- BEGIN GENERATED COMMANDS -->
| Command | Purpose |
| --- | --- |
| `init` | Install shell loaders without adding a variable. |
| `target` | Show the managed configuration file location. |
| `check` | Validate the managed configuration. |
| `update` | Check for or install a verified GitHub release update. |
| `list` | List managed variables. |
| `get` | Read one managed variable. |
| `import` | Preview or explicitly import variables from the current process environment. |
| `export` | Write all managed variables as an encrypted JSON backup using $ENVMAN_BACKUP_KEY. |
| `import-backup` | Preview or explicitly import variables from an encrypted JSON backup using $ENVMAN_BACKUP_KEY. |
| `set` | Create or replace one managed variable. |
| `unset` | Remove one managed variable. |
| `rename` | Rename one managed variable. |
| `validate` | Validate a variable without saving it. |
<!-- END GENERATED COMMANDS -->

All commands support `--json` where shown by `envman --help`; structured output is
preferred for automation. Use `--stdin` for values that must not appear in shell
history, and avoid `--value` for secrets.

## TUI

Run `envman` (or `envman --nocolor` when curses color pairs are unavailable).
Use **A** to add, **E** or **Enter** to edit, **R** to rename, **D** to delete
after confirmation, **B** to create an encrypted backup, **I** to preview process
imports, and **J** to preview an encrypted-backup import. **O** changes ordering,
**F** filters, **M** chooses filter scope, **[**/**]** scroll details, and
**Q**/**Esc** exits to a child shell.

## Encrypted backups

Export all managed variables to an authenticated encrypted JSON envelope, then
preview and selectively restore:

```bash
export ENVMAN_BACKUP_KEY="$(password-manager read envman-backup-key)"
envman export ./envman-backup.json
envman import-backup ./envman-backup.json
envman import-backup ./envman-backup.json --all --apply
```

Use `--replace` only when replacing a known collision. Keep the key separate from
the encrypted file; never treat the backup as permission to disclose its contents.

## Verified updates and receipts

```bash
envman update --check
envman update --check --json
envman update
```

`update` uses the trusted provider recorded in the private install receipt. A
missing, malformed, symlinked, untrusted, or downgrade receipt/update path must
fail closed; a failed replacement must preserve the previous working install.

## Canonical documentation

- [CLI reference](https://github.com/CruxExperts/envman/blob/v0.1.6/docs/guides/cli.md)
- [Encrypted backups and migration](https://github.com/CruxExperts/envman/blob/v0.1.6/docs/guides/backups-and-migration.md)
- [Terminal UI guide](https://github.com/CruxExperts/envman/blob/v0.1.6/docs/guides/tui.md)
- [Storage and shell loading](https://github.com/CruxExperts/envman/blob/v0.1.6/docs/reference/storage-and-shell-loading.md)
- [Installation sources and updates](https://github.com/CruxExperts/envman/blob/v0.1.6/docs/reference/install-source-and-updates.md)
