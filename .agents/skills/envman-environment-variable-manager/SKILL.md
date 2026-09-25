---
name: envman-environment-variable-manager
description: Manage Envman CLI and terminal UI workflows for durable environment variables, process or encrypted-backup imports, shell loaders, encrypted backups, verified GitHub installation or updates, and receipt behavior. Use for Envman commands, TUI controls, managed-variable safety, migration, or release updates; do not use for generic shell questions unrelated to Envman.
---

<!-- envman-skill-lock: version=0.1.9 source=src/envman/cli.py -->

# Envman

Use Envman to maintain validated, per-user environment variables without hand-editing
shell startup files. Prefer the CLI for automation and JSON output; use the curses
TUI for interactive inspection and editing.

## Operating workflow

1. Confirm the installed version and resolved store before changing state:

   ```bash
   envman --version
   envman target --json
   envman check --json
   ```

2. Inspect with `envman list --json`. Normal output masks sensitive values. Use
   `get NAME --reveal` or `list --reveal` only inside a caller that protects the
   complete output.
3. Preview imports and storage migrations before applying them. Review names,
   warnings, collisions, and source labels in the JSON result.
4. Make one explicit change or approved batch, then run `envman check --json`.
5. Create an encrypted export before a migration or other consequential batch.
6. Use `envman update --check --json` for update discovery; let the receipt direct
   the provider and verified asset path.

## Safety invariants

- Treat the managed configuration and process environment as sensitive. New
  saves encrypt the configuration with a separate private file key. A copy of
  both the key and ciphertext, or an unlocked process environment, exposes values.
  Protect their directories and permissions; check for legacy plaintext snapshots.
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

## Verified installation and update

The public installer supports Linux x86_64, CPython `>=3.12,<3.13`, and
`uv >=0.11`. It verifies the release manifest, immutable asset URLs, byte sizes,
SHA-256 hashes, wheel metadata, runtime constraints, host compatibility, and the
installed executable before writing the private receipt.

```bash
uv run --python 3.12 --script \
  https://github.com/CruxExperts/envman/releases/latest/download/install.py
export PATH="$(uv tool dir --bin):$PATH"
envman --version
envman check --json
```

Add `--install-skill` to install the verified release skill. `--skill-scope`
accepts `auto`, `repository`, or `global`; repeat `--skill-target AGENT` for
selected LocalSetup-supported agents or use `--skill-target all`. Automatic
placement prefers `.agents/skills` and refreshes existing supported native roots
such as `.codex/skills` and `.opencode/skills`. The installer rejects symlink
escapes and preserves an unmarked existing skill.

```bash
uv run --python 3.12 --script \
  https://github.com/CruxExperts/envman/releases/latest/download/install.py \
  --install-skill --skill-scope global --skill-target codex
```

For an existing receipt-directed installation:

```bash
envman update --check --json
envman update
envman update --install-skill --skill-scope repository --skill-target opencode
```

An update verifies the replacement before changing the receipt and retains the
previous verified wheel, constraints, and skill files for rollback. Skill
installation reads the latest verified GitHub release even when the Envman tool
is already current. A missing, malformed, symlinked, untrusted, or downgrade
receipt path fails closed.

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

Use `--stdin` when a value should stay out of command arguments:

```bash
printf '%s' "$API_TOKEN" | envman set API_TOKEN --stdin --json
```

`envman init` writes managed loader blocks while preserving profile content
outside those markers. Saving a value also refreshes the loaders. The TUI exits
to a child shell with the managed environment; CLI callers control when their
current process or a new shell loads the generated files.

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
| `migrate-storage` | Preview or encrypt historical plaintext environment snapshots. |
| `update` | Check for or install a verified GitHub release update. |
| `list` | List managed variables. |
| `get` | Read one managed variable. |
| `import` | Preview or explicitly import variables from the current process environment. |
| `export` | Write all managed variables as an encrypted JSON backup using $ENVMAN_BACKUP_KEY or the private key file. |
| `import-backup` | Preview or explicitly import variables from an encrypted JSON backup using $ENVMAN_BACKUP_KEY or the private key file. |
| `key` | Report or explicitly generate the encrypted-backup key. |
| `set` | Create or replace one managed variable. |
| `unset` | Remove one managed variable. |
| `rename` | Rename one managed variable. |
| `validate` | Validate a variable without saving it. |
<!-- END GENERATED COMMANDS -->

For encrypted-backup key setup, an AI agent MUST request both explicit switches:

```bash
envman key --generate --approve-key-generation
```

The command creates `${XDG_CONFIG_HOME:-$HOME/.config}/envman/encryption.key`
only when no `ENVMAN_BACKUP_KEY` or fallback key is configured. It preserves
existing key files, emits no key material, and `--yes`/`--force` never approve
generation. A malformed or insecure key file fails closed. The TUI shows a
centered approval popup before creating the same fallback; No/Esc leaves state
unchanged and encrypted-backup operations unavailable.

All commands support `--json` where shown by `envman --help`; structured output is
preferred for automation. Use `--stdin` for values that must not appear in shell
history, and avoid `--value` for secrets.

## Storage migration

`envman check --json` reports historical plaintext environment snapshots. Keep a
recoverable encrypted export, preview the conversion, apply it explicitly, and
validate the result:

```bash
envman export ./envman-recovery.json --json
envman migrate-storage --json
envman migrate-storage --apply --json
envman check --json
```

Migration encrypts the active store and historical environment snapshots while
preserving profile snapshots. It cannot remove copies held by external backups,
filesystem snapshots, or storage remnants. Keep the storage key separate from
copies of the encrypted store.

## TUI

Run `envman` (or `envman --nocolor` when curses color pairs are unavailable).
Use **A** to add, **E** or **Enter** to edit, **R** to rename, **D** to delete
after confirmation, **C** to copy a focused source into the selected targets,
**B** to create an encrypted backup, **I** to preview process imports, and **J**
to preview an encrypted-backup import. **Space** toggles selection; group copy,
delete, and backup use the selected rows and fall back to the focused row or full
catalog as documented when the selection is empty. **O** changes ordering, **F**
filters, **M** chooses filter scope, **[**/**]** scroll details, and **Q**/**Esc**
exits to a child shell.

The header reports the store, mode, ordering, filter, and selected count. The
`>` focus cue, `[ ]`/`[*]` selection markers, warnings, and status remain usable
without color. A terminal smaller than 80 columns by 18 rows pauses catalog
actions until it is resized.

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

Automation should treat every nonzero exit as a failed operation and preserve the
returned diagnostic. Do not retry an uncertain write blindly; run `check`, `list`,
or `update --check` to reconcile the observed state first.

## Canonical documentation

- [CLI reference](https://github.com/CruxExperts/envman/blob/v0.1.9/docs/guides/cli.md)
- [Encrypted backups and migration](https://github.com/CruxExperts/envman/blob/v0.1.9/docs/guides/backups-and-migration.md)
- [Terminal UI guide](https://github.com/CruxExperts/envman/blob/v0.1.9/docs/guides/tui.md)
- [Storage and shell loading](https://github.com/CruxExperts/envman/blob/v0.1.9/docs/reference/storage-and-shell-loading.md)
- [Installation sources and updates](https://github.com/CruxExperts/envman/blob/v0.1.9/docs/reference/install-source-and-updates.md)
