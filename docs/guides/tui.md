---
layout: default
title: Terminal UI
---

# Terminal UI

Run `envman` with no command to open the interactive catalog. The catalog is full-height and index-free: it uses the available rows between the fixed header and footer and never assigns numeric indexes to variables. The minimum supported terminal size is 80 columns by 18 rows. If the terminal is smaller, Envman shows a size message and ignores catalog actions until it is resized.

## Catalog controls

- **Up/Down** moves focus.
- **Space** toggles the focused variable in the multi-selection. Selected rows show `[*]`; focused but unselected rows show `[ ]`.
- **A** adds a variable.
- **Enter** or **E** edits the focused variable.
- **R** renames the focused variable.
- **C** copies one managed source value to every selected target. With no selected targets, it copies to the focused variable.
- **D** deletes every selected variable. With no selection, it deletes the focused variable after confirmation.
- **B** writes an encrypted backup of the selected variables. With no selection, it writes every managed variable.
- **I** opens a preview of variables from the current process environment.
- **J** opens a preview of an encrypted backup.
- **O** changes sort order; **F** edits the filter pattern; **M** changes whether the filter matches names, values, or both; **[** and **]** scroll the focused value details.
- **Q** or **Esc** leaves the catalog and reloads the managed environment in a child shell.

Selection is reconciled with the current filter. When a filter hides a selected variable, Envman removes that variable from the selection rather than applying a later group operation to an invisible row. In the process-environment and encrypted-backup previews, the same rule applies to selected source rows; **A** toggles all currently shown importable rows.

## Editing prompts

Prompts are line editors, not shell commands:

- **Enter** accepts the current text; **Esc** cancels it; **Backspace** removes the last character.
- Only printable characters are accepted. Variable-name prompts accept ASCII letters, digits, and underscores, convert letters to uppercase, convert `-` to `_`, and reject a leading digit.
- Secret prompts display one `*` per entered character.
- The prompt row is cleared before each redraw, so shorter replacement text cannot leave old characters behind. Input is preserved across a temporary undersized-terminal message and resumes after the terminal is resized.

The add and edit prompts validate the entered value before saving. A name that ends in `_API_KEY_ENV` is a managed-variable reference: its value must name another managed variable and is not treated as a secret itself. See [storage and shell loading](../reference/storage-and-shell-loading.md) for the complete name, value, masking, and shell-preservation rules.

Copying a sensitive value into a name that would display it as public is rejected. Renaming a sensitive value to a public name is rejected for the same reason. For import boundaries and collision handling, see [the CLI reference](cli.md) and [encrypted backups and migration](backups-and-migration.md).

Use `envman --nocolor` when a colorless curses surface is required.
