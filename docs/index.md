---
layout: default
title: Envman | Portable environment variables
description: Manage persistent environment variables from a Linux terminal UI or scriptable CLI.
---

<section class="hero" aria-labelledby="hero-title">
  <div class="hero-copy">
    <p class="status">release 0.1.3</p>
    <h1 id="hero-title">Manage persistent environment variables from a terminal UI or CLI.</h1>
    <p>Envman keeps a validated set of per-user variables in one managed file. Use the full-height terminal UI for interactive work or the CLI for repeatable commands and JSON output.</p>
    <div class="actions" aria-label="Primary actions">
      <a class="button" href="{{ '/getting-started/installation' | relative_url }}">Install 0.1.3</a>
      <a class="button secondary" href="{{ '/guides/tui' | relative_url }}">Terminal UI</a>
      <a class="button secondary" href="{{ '/guides/cli' | relative_url }}">CLI reference</a>
    </div>
  </div>
  <section class="panel" aria-label="Example Envman terminal output">
    <div class="panel-header"><span>envman / managed variables</span><span class="signal">sensitive values masked</span></div>
    <pre class="readout" aria-label="Example JSON output"><span class="status">$ envman list --json</span>
{"variables": [{"name": "OMNIROUTE_API_KEY", "sensitive": true, "value": "ab*******jk"}, {"name": "OMNIROUTE_BASE_URL", "sensitive": false, "value": "https://llm.example/v1"}, {"name": "PROJECT_PATH", "sensitive": false, "value": "/path/to/project"}]}</pre>
  </section>
</section>

## One managed file, two interfaces

<div class="columns">
  <section>
    <h3>Terminal UI</h3>
    <p>The catalog and selected-variable detail use the available terminal height instead of a fixed index. Arrow keys move the selection, and Space toggles multiple variables.</p>
  </section>
  <section>
    <h3>Scriptable CLI</h3>
    <p>Use <code>list</code>, <code>get</code>, <code>set</code>, <code>unset</code>, <code>rename</code>, <code>validate</code>, and import commands. Add <code>--json</code> for stable machine-readable output.</p>
  </section>
  <section>
    <h3>Encrypted migration</h3>
    <p>Export an authenticated encrypted JSON backup with <code>ENVMAN_BACKUP_KEY</code>. The TUI can back up the selected variables; the CLI exports the managed set.</p>
  </section>
</div>

## Safety rules are visible

- Names in the `KEY` class are sensitive, except names ending in `_API_KEY_ENV`, which reference another managed variable.
- Sensitive values are masked at the edges: 4+4 characters for values at least 16 characters long, 2+2 for 10-15, and 1+1 for 6-9. Sensitive values shorter than six characters are rejected.
- Normal output masks sensitive values. `--reveal` is an explicit opt-in for a caller that can protect the output.
- Import previews changes before applying them. `--force` accepts advisory warnings but does not bypass validation or collision protection.

## Install a verified release

Envman 0.1.3 requires Linux x86_64, CPython 3.12, and `uv >=0.11,<0.12`:

```bash
uv run --python 3.12 --script https://github.com/CruxExperts/envman/releases/latest/download/install.py
ENVMAN="$(uv tool dir --bin)/envman"
"$ENVMAN" --version
```

The standalone installer verifies the GitHub release manifest, immutable asset URLs, SHA-256 hashes, wheel metadata, runtime constraints, and the selected `uv` runtime before installing with `uv tool install --no-build`. It resolves the installed command through `uv tool dir --bin`, so installation and verification succeed even if that directory is not yet in `PATH`. It records an installation receipt under `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`; updates use that recorded provider and do not silently switch channels. [Read the installation trust boundary.]({{ '/reference/install-source-and-updates' | relative_url }})

## Where state lives

```text
${XDG_CONFIG_HOME:-$HOME/.config}/envman/environment.conf
  -> load-env.sh and shell-specific loaders
  -> backups/ (local tar.gz snapshots before managed-file writes)

${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json
  -> installer receipt used by verified updates
```

Start with:

- [Install Envman]({{ '/getting-started/installation' | relative_url }})
- [Use the terminal UI]({{ '/guides/tui' | relative_url }})
- [Automate with the CLI]({{ '/guides/cli' | relative_url }})
- [Move variables with encrypted backups]({{ '/guides/backups-and-migration' | relative_url }})
- [Understand storage and shell loading]({{ '/reference/storage-and-shell-loading' | relative_url }})
- [Read the installation and update protocol]({{ '/reference/install-source-and-updates' | relative_url }})
- [Read the architecture]({{ '/development/architecture' | relative_url }})
- [Run the tests]({{ '/development/testing' | relative_url }})
- [Plan and publish a release]({{ '/development/versioning-and-releases' | relative_url }})
- [Use the publishing checklist]({{ '/governance/publishing-checklist' | relative_url }})
