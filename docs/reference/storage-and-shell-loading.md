---
layout: default
title: Storage and shell loading
---

# Storage and shell loading

Envman stores managed values in `${XDG_CONFIG_HOME:-$HOME/.config}/envman/environment`. The file is loaded through a managed block in supported shell startup files. Envman owns only text between these markers:

```text
# >>> envman environment >>>
# <<< envman environment <<<
```

`envman init` creates the config directory and installs loader blocks without adding a variable. `envman target` reports the managed file. Existing shell content outside the markers remains untouched.

Values are validated before saving: names use portable shell identifier syntax, control characters are rejected, URLs are normalized, missing path components become warnings, and names or URLs that indicate secrets are masked in normal presentation. A variable whose name ends in `_API_KEY_ENV` is a reference name rather than a secret value and remains visible.
