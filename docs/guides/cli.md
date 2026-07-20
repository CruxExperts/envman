---
layout: default
title: CLI reference
---

# CLI reference

Commands operate on the managed store without opening the TUI. Every command supports `--json` for a stable machine-readable result. Human-readable output masks sensitive values; only `list` and `get` provide `--reveal`, and that option should be used only by a caller that can protect its output.

## Store and inspect values

```bash
envman init
envman target --json
envman set PROJECT_URL --value 'https://example.test'
envman get PROJECT_URL
envman list --json
envman validate PROJECT_PATH --value "$HOME/project"
envman check
envman unset PROJECT_URL
```

- `init` installs the shell loaders without adding a variable.
- `target` prints the managed file path.
- `set` creates or replaces one variable. Supply exactly one of `--value`, `--stdin`, or `--from NAME`.
- `get` reads one managed variable; `list` reads all managed variables.
- `validate` applies the same validation as `set` without saving.
- `check` validates the managed file.
- `unset` removes one variable; `rename OLD_NAME NEW_NAME` changes one name after validating the new name.

`--stdin` reads a literal value, which avoids putting a secret in command arguments. `--from NAME` copies a managed value. A literal passed to `--value` that names an existing managed variable is also resolved as a copy; use a value source that is unambiguous for your automation. `--force` and `--yes` accept advisory warnings only. They never bypass required validation or collision protection.

## Process-environment import

`import` first previews candidates from the current process environment:

```bash
APP_TOKEN='example-token-value' envman import APP_TOKEN
APP_TOKEN='example-token-value' envman import APP_TOKEN --apply
APP_TOKEN='replacement-token-value' envman import APP_TOKEN --apply --replace
envman import --all --apply
```

Without `--apply`, nothing is saved. Applying requires explicit names or `--all`; names and `--all` cannot be combined. A selected candidate that would replace a different managed value is a collision and requires `--replace`. Existing managed names are reported as unchanged when their value already matches. `--force` and `--yes` suppress advisory warnings, including missing path-component warnings, but do not make an invalid candidate importable.

Imports preserve the process value bytes. URL names are checked for valid URL syntax, and `PATH` names must contain only absolute path entries; unlike interactive entry, import does not rewrite those values. Names that end in `_API_KEY_ENV` must reference an importable or already managed variable. See [storage and shell loading](../reference/storage-and-shell-loading.md) for validation, secret masking, and persistence details.

## Encrypted backup commands

Populate `ENVMAN_BACKUP_KEY` through a password manager or another trusted mechanism that does not record the value in shell history. Then run:

```bash
envman export ./envman-backup.json
envman import-backup ./envman-backup.json --all --apply
```

`export` writes every managed variable to an authenticated encrypted JSON envelope. `import-backup` previews candidates unless `--apply` is supplied; use names or `--all` to choose the candidates and `--replace` for intentional managed-name collisions. See [encrypted backups and migration](backups-and-migration.md) for the envelope, file permissions, and migration procedure.

## Verified updates

```bash
envman update --check
envman update --check --json
envman update
```

`update --check` reports whether a newer verified GitHub release is available without installing it. `update` uses only the provider recorded in the private install receipt and verifies the manifest and release assets before replacing the tool. A missing, malformed, symlinked, or untrusted receipt is an error; Envman does not silently choose another update source. See [installation sources and updates](../reference/install-source-and-updates.md).

## Copy and rename boundaries

The same rules apply to TUI and CLI operations:

- Empty values are not copied. A sensitive value cannot be copied or renamed to a name that would expose it as public.
- `rename` validates the destination name and rejects a sensitive-to-public transition.
- Secret names and credential-bearing URL values are masked by default. A `_API_KEY_ENV` name is a reference to a managed variable, not a secret value.
- Secret values must contain at least six characters. `--force` does not relax this minimum.

For the interactive multi-selection and focused-variable fallbacks, see [the terminal UI guide](tui.md).
