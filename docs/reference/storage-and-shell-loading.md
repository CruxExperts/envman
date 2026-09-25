---
layout: default
title: Storage and shell loading
---

# Storage and shell loading

Envman stores managed assignments in:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/envman/environment.conf
```

When Envman creates the directory it uses mode `0700`; `environment.conf` and the generated loader files are written with mode `0600`. New saves encrypt the complete configuration with an authenticated format, including comments and assignment order. The random storage key is a different file at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/storage.key`, with mode `0600` in a private directory. `XDG_CONFIG_HOME` and `XDG_STATE_HOME`, when set, must be absolute paths. `envman target` prints the resolved data path. `envman init` creates the directory and installs shell loaders without adding a variable; saving a variable also installs or refreshes them.

The private file key permits loading in desktop, SSH, and unattended sessions without a new prompt. It protects a copy of the encrypted data file alone. Copying the key with the data, or acting as the unlocked user or root, permits decryption. Keep the key and encrypted data in separate backup and access boundaries. A lost key without a recoverable encrypted export makes the managed file unreadable. The storage key is distinct from the encrypted-export credential below.

## Encrypted-backup key storage

If `ENVMAN_BACKUP_KEY` is explicitly configured, encrypted backups use it. If it is unset, Envman may use `${XDG_CONFIG_HOME:-$HOME/.config}/envman/encryption.key` as a generated private fallback with mode `0600`. Envman never creates or replaces the fallback silently. TUI startup prompts before generation; declining leaves state unchanged and encrypted-backup operations unavailable.

Automation and AI agents must invoke `envman key --generate --approve-key-generation`. `--yes` and `--force` are not approval. Key-generation output never prints key material, existing key files are preserved, and malformed key files fail closed. The installer itself does not generate this key.

## Shell loaders and preservation

Envman writes `${XDG_CONFIG_HOME:-$HOME/.config}/envman/load-env.sh` for POSIX shells and `${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/envman.fish` for fish. The POSIX loader is sourced from managed blocks marked:

```text
# >>> envman environment >>>
# <<< envman environment <<<
```

The blocks are added to `$HOME/.profile`, an existing `.bash_profile` or `.bash_login` (the first one found), and `.bashrc`, `.zprofile`, and `.zshrc`. Envman appends a block only when that profile does not already contain its marker. Text, comments, and assignments outside the markers remain untouched. A private retained decryptor and copy of its crypto library keep the generated loaders usable if the Envman application is later removed. The Python interpreter used by the loader must remain available. Missing keys or damaged ciphertext prevent any managed assignments from loading; the loader reports an error without exposing values.

The environment file keeps existing comments and managed assignment positions when possible, updates values in place, removes deleted assignments, and appends new names in sorted order. Envman creates timestamped private tar-gzip backups before replacing an existing managed file. New environment snapshots contain ciphertext. Existing plaintext snapshots from earlier versions remain sensitive until migrated. `envman check` reports their count; `envman migrate-storage` previews, and `envman migrate-storage --apply` encrypts the active file and historical environment snapshots. If a storage key exists alongside an active plaintext file, normal loading refuses it; use the explicit migration command to recover that interrupted state. Migration preserves profile snapshots and their contents.

## Validation and secret display

Names must be ASCII shell identifiers: a letter or underscore followed by letters, digits, or underscores. Interactive and CLI name entry normalizes hyphens to underscores and letters to uppercase. Values reject control characters and invalid UTF-8. Names containing `URL` require a syntactically valid URL; HTTP and HTTPS URLs require a host. Names containing `PATH` require absolute path entries, which Envman resolves and reports as warnings when they do not exist. Imported process values are checked without rewriting their bytes.

Envman treats a name as sensitive when it contains a credential class such as `API_KEY`, `API_SECRET`, `SECRET`, `TOKEN`, `PASSWORD`, `CREDENTIAL`, `PRIVATE_KEY`, `ENCRYPTED`, or a standalone `KEY` component. `KEY` is not a substring rule: names such as `KEYSTONE` and `MYKEYVALUE` are not sensitive. In entry and import workflows, a name ending in `_API_KEY_ENV` is a managed-variable reference exception; its value must name another managed variable and is displayed as a reference rather than a secret. A URL-named value is also sensitive when its parsed URL contains a password.

Sensitive values are masked as follows:

- 4 visible characters at each edge for values of length 16 or more;
- 2 at each edge for lengths 10 through 15;
- 1 at each edge for lengths 6 through 9;
- all characters masked for shorter values.

Every sensitive value must contain at least six characters, including values arriving through imports and encrypted-backup restores. The literal placeholder `change me` is displayed as entered rather than masked, but it is still validated like any other value. Normal output stays masked; the CLI exposes a sensitive value only when `list --reveal` or `get --reveal` is explicitly requested.

For TUI selection and prompt behavior, see [the terminal UI guide](../guides/tui.md). For CLI import, copy, rename, and collision boundaries, see [the CLI reference](../guides/cli.md). For encrypted file migration, see [encrypted backups and migration](../guides/backups-and-migration.md).
