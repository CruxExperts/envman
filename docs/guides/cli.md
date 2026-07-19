---
layout: default
title: CLI reference
---

# CLI reference

Use `--json` on commands that support automation. Sensitive values remain masked unless the caller explicitly passes `--reveal` where supported.

```bash
envman init
envman target --json
envman set PROJECT_URL --value https://example.test
envman get PROJECT_URL
envman list --json
envman validate PROJECT_PATH --value /srv/project
envman unset PROJECT_URL
envman check
```

`set` and `validate` accept `--stdin` for sensitive values and `--from NAME` to copy a managed value. `import` previews process-environment candidates and needs `--apply` plus explicit names or `--all` to persist them. `--force` accepts advisory warnings but never bypasses validation or collision protection.

```bash
printf '%s' "$API_TOKEN" | envman set API_TOKEN --stdin
envman import PATH HOME --apply
envman list --json
```

Use `envman update --check --json` for a schema-versioned update result.
