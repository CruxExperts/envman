# Design

## Surface

Envman has two public interaction surfaces: a curses TUI for deliberate local editing and a CLI for repeatable commands. Both operate on the same per-user managed store and apply the same name, value, URL, path, and sensitive-value validation.

## TUI layout

The catalog is full-height and index-free. Its fixed chrome contains the title, managed-file location, sort and filter controls, a status line, and a detail area; the variable list uses the remaining terminal height. The minimum supported surface is 80 columns by 18 rows.

Each row shows a selection marker, name, and display value. The focused row is visually distinct. Sensitive values are masked, and the selected detail view uses the same display policy as the catalog. A colorless launch uses text and weight rather than color alone.

## TUI interaction

`Up` and `Down` move focus. `Space` toggles membership in the current multi-selection. `C`, `D`, and `B` apply copy, delete, and encrypted-backup actions to the selected group; with no selection they apply to the focused variable or, for backup, to all managed variables. `A`, `E`/`Enter`, and `R` add, edit, and rename. `O`, `F`, and `M` control ordering and filtering. `I` imports from the process environment, and `J` imports from an encrypted backup.

Prompts occupy the status row and clear that row before each redraw. `Q` and `Esc` leave the catalog; the normal no-command launch then starts a child shell with the managed environment.

## Visual rules

- Keep names and values visibly distinct without exposing sensitive values.
- Use selection markers and text labels so color is never the only state cue.
- Keep prompts, warnings, and save results in the status row rather than overwriting catalog content.
- Keep controls compact enough for the minimum terminal size and clip long values instead of wrapping list rows.
- Keep a colorless path (`envman --nocolor`) usable for terminals that do not support curses color pairs.

## Boundary

The TUI is an operator surface, not an encrypted vault. File permissions, process-environment handling, encrypted backup export, and release verification are separate controls documented in [the storage reference](docs/reference/storage-and-shell-loading.md), [the backup guide](docs/guides/backups-and-migration.md), and [the installation reference](docs/reference/install-source-and-updates.md).
