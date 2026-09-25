---
layout: default
title: Envman | Portable environment variables
description: Manage persistent Linux environment variables with a terminal UI, scriptable CLI, and encrypted backups.
---

<section class="home-stage" aria-labelledby="hero-title">
  <div class="home-stage__inner">
    <div class="home-stage__copy">
      <p class="release-line">Envman 0.1.9 · Linux x86_64</p>
      <h1 id="hero-title">Persistent variables, without the startup-file sprawl.</h1>
      <p>Envman keeps a validated set of per-user environment variables in one managed location. Inspect and edit them in the terminal UI, or use the CLI for repeatable commands and JSON output.</p>
      <div class="actions" aria-label="Primary actions">
        <a class="button" href="{{ '/getting-started/installation' | relative_url }}">Install Envman</a>
        <a class="button secondary" href="https://github.com/CruxExperts/envman">View on GitHub</a>
      </div>
    </div>
    <figure class="product-frame">
      <img src="{{ '/assets/terminal-preview.svg' | relative_url }}" width="1120" height="690" alt="Envman terminal catalog showing a project path, service URL, masked API token, focused-row details, and keyboard controls">
      <figcaption>Sample data only. Sensitive values remain masked in ordinary output.</figcaption>
    </figure>
  </div>
</section>

<section class="home-section" aria-labelledby="two-interfaces">
  <h2 id="two-interfaces">One managed set. Two useful interfaces.</h2>
  <p class="home-section__intro">The TUI and CLI work on the same store and apply the same validation, masking, and persistence rules.</p>
  <div class="interface-pair">
    <section>
      <h3>Terminal UI for deliberate edits</h3>
      <p>Browse the complete catalog, focus a value, select several variables, and preview imports before saving. The layout uses the available terminal height and keeps its controls visible at 80 by 18 characters.</p>
      <p><a href="{{ '/guides/tui' | relative_url }}">Learn the terminal controls →</a></p>
    </section>
    <section>
      <h3>CLI for scripts and automation</h3>
      <p>Use <code>list</code>, <code>get</code>, <code>set</code>, <code>rename</code>, <code>validate</code>, and import commands. Add <code>--json</code> where supported for stable machine-readable results.</p>
      <p><a href="{{ '/guides/cli' | relative_url }}">Read the CLI reference →</a></p>
    </section>
  </div>
</section>

<section class="home-section home-section--brand" aria-labelledby="storage-boundary">
  <div class="boundary-grid">
    <div>
      <h2 id="storage-boundary">The storage boundary stays explicit.</h2>
      <p>Envman encrypts the managed configuration after its first save and keeps the storage key in a separate private state file. Encrypted exports use an independent backup credential.</p>
      <p><a href="{{ '/reference/storage-and-shell-loading' | relative_url }}">Understand storage and shell loading →</a></p>
    </div>
    <ul class="boundary-list">
      <li><strong>Masked output</strong>Values classified as sensitive by their names, plus password-bearing URLs, are masked unless a trusted caller explicitly requests <code>--reveal</code>.</li>
      <li><strong>Preview before import</strong>Process and backup imports show their proposed changes before <code>--apply</code> writes anything.</li>
      <li><strong>Separate backup key</strong><code>ENVMAN_BACKUP_KEY</code> or an approved private fallback protects encrypted backup files.</li>
      <li><strong>Verified releases</strong>The installer checks immutable asset URLs, sizes, hashes, wheel metadata, runtime constraints, and host compatibility.</li>
    </ul>
  </div>
</section>

<section class="home-section home-section--tint" aria-labelledby="quick-start">
  <div class="quickstart">
    <div>
      <h2 id="quick-start">Install the verified release.</h2>
      <p>Envman 0.1.9 supports Linux x86_64, CPython 3.12, and <code>uv &gt;=0.11</code>.</p>
      <a class="button" href="{{ '/getting-started/installation' | relative_url }}">Installation details</a>
    </div>
    <pre aria-label="Envman installation command"><code>uv run --python 3.12 --script \
  https://github.com/CruxExperts/envman/releases/latest/download/install.py

# Add uv's tool bin directory to this shell, then open Envman:
export PATH="$(uv tool dir --bin):$PATH"
envman</code></pre>
  </div>
</section>

<section class="home-section" aria-labelledby="documentation">
  <h2 id="documentation">Go straight to the useful page.</h2>
  <p class="home-section__intro">Start with the task in front of you. Protocol and architecture details are there when you need to inspect the boundary.</p>
  <div class="route-list">
    <a href="{{ '/getting-started/installation' | relative_url }}">Install and update</a>
    <a href="{{ '/guides/tui' | relative_url }}">Use the terminal UI</a>
    <a href="{{ '/guides/cli' | relative_url }}">Automate with the CLI</a>
    <a href="{{ '/guides/backups-and-migration' | relative_url }}">Move encrypted backups</a>
    <a href="{{ '/reference/storage-and-shell-loading' | relative_url }}">Inspect storage behavior</a>
    <a href="{{ '/reference/install-source-and-updates' | relative_url }}">Inspect release verification</a>
    <a href="{{ '/development/architecture' | relative_url }}">Read the architecture</a>
    <a href="{{ '/development/testing' | relative_url }}">Run the test suite</a>
  </div>
</section>
