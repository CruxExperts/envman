---
layout: default
title: Storage and shell loading
---

# Storage and shell loading

Envman stores managed assignments in:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/envman/environment.conf
```

When Envman creates the directory it uses mode `0700`; `environment.conf` and the generated loader files are written with mode `0600`. `XDG_CONFIG_HOME`, when set, must be an absolute path. `envman target` prints the resolved path. `envman init` creates the directory and installs shell loaders without adding a variable; saving a variable also installs or refreshes the loaders.

## Shell loaders and preservation

Envman writes `${XDG_CONFIG_HOME:-$HOME/.config}/envman/load-env.sh` for POSIX shells and `${XDG_CONFIG_HOME:-$HOME/.config}/fish/conf.d/envman.fish` for fish. The POSIX loader is sourced from managed blocks marked:

```text
# >>> envman environment >>>
# <<< envman environment <<<
```

The blocks are added to `$HOME/.profile`, an existing `.bash_profile` or `.bash_login` (the first one found), and `.bashrc`, `.zprofile`, and `.zshrc`. Envman appends a block only when that profile does not already contain its marker. Text, comments, and assignments outside the markers remain untouched. The generated loaders remain usable if the Envman application is later removed.

The environment file keeps existing comments and managed assignment positions when possible, updates values in place, removes deleted assignments, and appends new names in sorted order. Envman creates timestamped mode-`0600` tar-gzip backups before replacing an existing managed file.

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
