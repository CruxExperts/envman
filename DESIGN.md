# Design

## Surface

Envman has two public interaction surfaces: a curses TUI for deliberate local editing and a CLI for repeatable commands. Both operate on the same per-user managed store and apply the same name, value, URL, path, and sensitive-value validation.

## TUI layout

The catalog is full-height and index-free. Its fixed chrome contains the title, store location, current mode, sort and filter controls, a selection total, a status line, and a detail area; the variable list uses the remaining terminal height. The minimum supported surface is 80 columns by 18 rows.

Each row uses aligned name and value columns. It shows a selection marker and a separate `>` focus cue, so selection and keyboard focus cannot be confused. The focused row uses a strong reverse-video treatment when color is available. Sensitive values are masked, and the selected detail view uses the same display policy as the catalog. A colorless launch keeps the focus cue and uses weight rather than color alone.

## TUI interaction

`Up` and `Down` move focus. `Space` toggles membership in the current multi-selection. `C`, `D`, and `B` apply copy, delete, and encrypted-backup actions to the selected group; with no selection they apply to the focused variable or, for backup, to all managed variables. `A`, `E`/`Enter`, and `R` add, edit, and rename. `O`, `F`, and `M` control ordering and filtering. `I` imports from the process environment, and `J` imports from an encrypted backup.

Prompts occupy the status row and clear that row before each redraw. `Q` and `Esc` leave the catalog; the normal no-command launch then starts a child shell with the managed environment.

## Visual rules

- Keep names and values visibly distinct without exposing sensitive values.
- Use selection markers and text labels so color is never the only state cue.
- Use cyan for the active interface vocabulary, neutral text for values, and yellow only for collisions or warnings.
- Show current selection, visible-row, and importable-row totals above the catalog.
- Keep prompts, warnings, and save results in the status row rather than overwriting catalog content.
- Keep controls compact enough for the minimum terminal size and clip long values instead of wrapping list rows.
- Keep a colorless path (`envman --nocolor`) usable for terminals that do not support curses color pairs.

## Public identity and documentation site

The public identity is built around a bracketed equals mark: `[=]`. Mineral teal and deep ink carry the main surfaces, while a high-visibility yellow-green is reserved for primary actions and live status. The site uses a bright reading surface around a dark product stage, rather than turning every documentation page into a terminal imitation.

The GitHub README and Pages site share the same wordmark, terminal preview, install path, product boundaries, and documentation routes. Public pages use system fonts, keep body copy under 74 characters per line, preserve visible keyboard focus, adapt to light and dark preferences, and remove motion for users who request reduced motion. The synthetic product preview contains no real environment values.

Original visual assets live under `docs/assets/`. SVG is the editable source format. The 1280 by 640 PNG is the repository and page social image; it is derived from `social-preview.svg` and carries the asset ownership metadata required by the repository policy.

## Boundary

The TUI is an operator surface over an encrypted local store. File-key protection, process-environment handling, encrypted backup export, and release verification are separate controls documented in [the storage reference](docs/reference/storage-and-shell-loading.md), [the backup guide](docs/guides/backups-and-migration.md), and [the installation reference](docs/reference/install-source-and-updates.md).
