---
layout: default
title: Terminal UI
---

# Terminal UI

Run `envman` with no command to open the interactive catalog. The UI lists managed variables, masks sensitive values, and keeps sort/filter controls visible above the catalog.

- Use **Enter** to edit the selected value.
- Use **E** to export an encrypted backup.
- Use **I** to inspect and selectively import variables.
- Use **Q** or **Esc** to leave the catalog.
- Use `envman --nocolor` when a colorless curses surface is required.

When an entered value names an existing managed variable, Envman resolves and copies its value rather than persisting the variable name. Credential warnings are shown as an explicit decision card; they do not bypass validation.
