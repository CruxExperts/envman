---
layout: default
title: Terminal UI
---

# Terminal UI

Run `envman` with no command to open the interactive catalog. The catalog expands to the available terminal height, masks sensitive values, and keeps sort/filter controls visible above the list.

- Use **Up/Down** to move focus and **Space** to toggle one or more variables.
- Use **A** to add, **Enter** or **E** to edit, and **R** to rename the focused variable.
- Use **C** to copy one source value into every selected variable, or into the focused variable when nothing is selected.
- Use **D** to delete the selected variables, or the focused variable when nothing is selected.
- Use **B** to export selected variables as an encrypted backup. With no selection, the backup includes every managed variable.
- Use **I** to preview and selectively import process variables. Use **J** to preview an encrypted backup before importing.
- Use **O** to change ordering, **F** to set a filter, **M** to change filter scope, and **[** or **]** to scroll value details.
- Use **Q** or **Esc** to leave the catalog and reload the managed environment into a child shell.
- Use `envman --nocolor` when a colorless curses surface is required.

When an entered value names an existing managed variable, Envman resolves and copies its value rather than persisting the variable name. Credential warnings are shown as an explicit decision card; they do not bypass validation.
