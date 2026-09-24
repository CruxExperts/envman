---
layout: default
title: Architecture
---

# Architecture

## Application boundary

Envman's runtime is a small Python 3.12 package. `src/envman/cli.py` owns the command-line parser, terminal UI, persistent environment store, validation and masking rules, shell-loader installation, import flows, and encrypted backups. `src/envman/_release_protocol.py` is intentionally standard-library-only because the committed `install.py` is generated from it and runs with `uv run --script`.

The project has no web framework, Node toolchain, linter dependency, or test-framework dependency in its runtime. Hatchling reads the single `VERSION` file for package metadata. The CLI reads installed distribution metadata and falls back to that source-checkout file when the package is not installed.

The small scripts have separate boundaries:

- `scripts/version.py` plans and checks the patch-default Conventional Commit release policy.
- `scripts/render_installer.py` renders `install.py` from `_release_protocol.py`.
- `scripts/release_assets.py` creates the pinned runtime-constraints projection, release manifest, and SHA-256 list.
- `scripts/check_docs.py` checks that every machine-index path exists and is linked by `docs/INDEX.md`.

## Managed state

`XDG_CONFIG_HOME` must be an absolute path when set. Otherwise Envman uses `$HOME/.config`. The managed file is `envman/environment.conf`; writes use a temporary file, mode `0600`, and a timestamped `0600` tar.gz snapshot under `envman/backups/` before replacement. The utility directory is created with mode `0700` and symlinked targets are rejected.

`envman init` installs loaders without adding a variable. The POSIX loader is `load-env.sh`; Envman adds guarded loader blocks to the supported profile files and writes a Fish loader at `fish/conf.d/envman.fish`. Existing profile content is preserved, and each profile is backed up before a loader block is added.

## Terminal UI and CLI

The TUI requires at least 80 columns by 18 rows. Its catalog capacity is computed from the current terminal height, so the catalog and detail view use the full available area instead of a fixed page index. Arrow keys move the current row, `[` and `]` scroll detail text, and Space toggles a variable in the multi-selection. `C` copies one source value to the selected targets, `D` deletes the selected group after confirmation, and `B` exports the selected group as an encrypted backup. At startup, when neither encryption-key source is configured, the TUI shows a centered approval modal before generating a private fallback key; `No` or `Esc` leaves state unchanged and encrypted-backup operations unavailable. Every prompt clears the prompt row before drawing its next frame.

The CLI exposes `init`, `target`, `check`, `update`, `list`, `get`, `import`, `export`, `import-backup`, `set`, `unset`, `rename`, `validate`, and `key`. Commands accept `--json` for stable machine-readable output. Sensitive values stay masked unless a caller explicitly supplies `--reveal`; `--force` and `--yes` suppress advisory warnings only, while key generation requires both `--generate` and `--approve-key-generation`.

Sensitivity is name- and value-aware. `KEY`-class names are sensitive, except names ending in `_API_KEY_ENV`, which are references to another managed variable. Sensitive values shorter than six characters are rejected. Masks show 1+1 characters for lengths 6-9, 2+2 for 10-15, and 4+4 for lengths of at least 16. URLs containing a password are also treated as sensitive.

Encrypted backups prefer the `ENVMAN_BACKUP_KEY` environment variable and otherwise use the private mode-`0600` fallback key file under the Envman configuration directory. The fallback is created only after the TUI approval modal or the CLI's explicit `key --generate --approve-key-generation` approval; malformed or insecure key files fail closed. Backups use an authenticated Fernet envelope with an scrypt-derived key. The JSON envelope contains the schema, version, creation time, KDF parameters, and ciphertext. Import validates the envelope and previews selected changes before applying them.

## Release protocol

The generated installer and the `update` command share `_release_protocol.py`. They accept only the exact release-manifest schema for `CruxExperts/envman`, Linux x86_64, Python `>=3.12,<3.13`, and `uv >=0.11`. Manifest assets must use immutable GitHub release URLs and declare bounded sizes and lowercase SHA-256 hashes. Downloads accept only GitHub-controlled HTTPS redirects; the wheel's Envman name and version, and every runtime constraint pin, are checked before installation.

Installation uses `uv tool install --no-build` and writes a private receipt at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. The receipt records the installed version, provider, manifest URL, asset metadata, installer version, `uv` version, and timestamp. Replacing an existing Envman tool requires a valid Envman receipt; updates use the recorded provider and refuse a downgrade. A failed replacement attempts to restore the previous wheel and receipt.

## Deterministic release assets

`install.py` must be rendered from the canonical protocol and committed without a diff:

```bash
uv run --locked --no-sync python scripts/render_installer.py
git diff --exit-code -- install.py
```

The tag-gated GitHub release workflow sets `SOURCE_DATE_EPOCH` to the tagged commit timestamp, builds twice with `uv build --no-build-isolation`, and compares the wheel and source archive byte-for-byte. `scripts/release_assets.py` then writes exact runtime pins from `uv.lock`, legacy and v2 release manifests, the version-locked agent skill, and `SHA256SUMS.txt`. The publish job creates a draft release from the matching changelog section, attests every release asset, and makes the release public only after those steps succeed.

## Proposed encrypted storage

Status: PROPOSAL, reviewed 2026-09-24. This section describes future work;
the application still stores its active configuration and automatic snapshots
in plaintext. The requirement is to preserve desktop, SSH, and unattended use
without prompting on each command or shell startup.

### Findings in the current implementation

`EnvironmentStore.write_values()` writes plaintext assignments, and `backup()`
copies the previous file into an unencrypted tar archive. Explicit encrypted
exports do not protect either surface. Both generated shell loaders read the
plaintext file directly and intentionally work after the application is removed.

The write path also uses a predictable temporary filename, writes before setting
permissions, and does not exclusively create that temporary file. A preexisting
symlink can redirect the write; preexisting permissive directories or files can
expose bytes before permissions are tightened. Snapshot names have only second
resolution and can overwrite an earlier snapshot. These are source-review
findings, not evidence of exploitation. Malformed-line errors in `load()` can
also print input content and should be redacted.

### Recommended design

Encrypt the complete rendered configuration, including comments and ordering,
with a randomly generated storage key. Use authenticated encryption through the
existing `cryptography` dependency; its Fernet API is a suitable starting point.
Keep a distinct, versioned storage envelope with an authenticated format marker
inside the encrypted payload. Validate bounded inputs and reject unsupported
formats. Fernet reveals token creation time and approximate payload size; it
does not hide all metadata. See the [Fernet documentation](https://cryptography.io/en/latest/fernet/).

Keep `EnvironmentStore.values`, validation, masking, imports, and TUI behavior as
the shared application boundary. Decrypt only in memory. Encrypt all variables,
regardless of whether the display heuristic labels their names sensitive. Keep
portable backup formats and their existing password derivation separate; do not
use `ENVMAN_BACKUP_KEY` as the storage unlock mechanism or derive a password key
on every shell startup.

Select and persist an explicit key provider during setup. For one store shared
by desktop and SSH/automation, choose a provider available in all those sessions;
a desktop-only keyring cannot satisfy that requirement on its own:

- **Desktop:** use an encrypted login keyring through Secret Service when it is
  available and unlocked. Normal password login can unlock GNOME Keyring without
  an additional Envman prompt. Public-key SSH, automatic login, and missing
  session services cannot be assumed to do this. The API alone does not guarantee
  the provider's encryption policy. See [Secret Service](https://specifications.freedesktop.org/secret-service/latest-single/)
  and [GNOME login unlocking](https://wiki.gnome.org/Projects/GnomeKeyring/Pam).
- **Headless:** use a provisioned noninteractive key source. Hardware-bound
  credentials are a stronger optional backend where supported; hardware access,
  boot policy, service identity, and actual SSH/automation access must be tested
  before enabling it. This is a capability-dependent integration, not a portable
  default. See [systemd credentials](https://systemd.io/CREDENTIALS/).
- **Portable compatibility:** offer an explicitly selected random key file,
  created mode `0600` in a verified private directory separate from data and
  snapshots. This avoids repeated prompts and protects a copied data file, but
  anyone who copies both key and ciphertext can decrypt it. Moving the key to
  another directory does not protect a complete home or disk copy.

Never silently fall back from a keyring or hardware provider to a file key, or
from encrypted storage to plaintext. Missing keys must not create replacement
keys for an existing store. Storage keys must never enter managed variables,
command arguments, logs, or child-process environments.

### Preserving shell behavior

Replace direct file reads with a small decrypting loader that authenticates and
validates the complete payload before emitting any assignments. Shell wrappers
must import literal name/value pairs without evaluating their contents as code;
preserve spaces, equals signs, Unicode, and shell metacharacters exactly. Do not
create a persistent decrypted cache. Use a bounded, noninteractive key lookup;
failure reports a concise diagnostic and supplies no partial managed environment.
An explicit automation entry point must return failure so a job can stop. An
interactive shell may remain usable after reporting failure; inherited values
cannot be described as freshly loaded or revoked.

Keeping the existing removal guarantee requires a separately retained loader
runtime, including its crypto dependency and key-provider access, with an owned
update and removal lifecycle. A wrapper that invokes the removed `envman` command
does not satisfy that guarantee. Full removal of all decrypting components cannot
preserve automatic loading from encrypted data. This packaging contract must be
resolved before enabling encrypted storage by default.

### Migration, recovery, and acceptance

Use exclusive temporary-file creation at mode `0600`, verified directory and
file ownership, descriptor-based symlink protection, atomic replacement, and
durable writes. Serialize mutations across processes and use collision-resistant
snapshot names. New snapshots must contain ciphertext, with retained keys for
their generations. Encryption does not itself prevent rollback to an older valid
snapshot or concurrent lost updates.

Before migration, prove key retrieval in every required session type and verify
an independently recoverable encrypted export. Under a writer lock, stage and
read back the encrypted configuration and loaders, verify exact values, and
switch using a recoverable transaction. Include historical environment snapshots
and potentially sensitive profile snapshots in the migration inventory. Convert
and verify retained copies before any authorized plaintext cleanup; never delete
history as an incidental side effect. Interrupted migration must leave a known
readable state and must not let old loaders interpret ciphertext as assignments.
Deleting files cannot guarantee erasure from storage snapshots, external backups,
or SSD remnants. Recovery must not depend solely on the original machine's keyring
or hardware; test portable backup restoration with a separately retained key.

Acceptance requires existing storage, CLI, TUI, and backup regressions plus tests
for wrong/missing keys, tampering, unsafe paths and modes, concurrent saves,
snapshot collisions, interrupted migration, key rotation, and exact shell values.
Exercise POSIX and fish loading, public-key SSH, unattended jobs, locked/missing
keyrings, restart, offline operation, and application removal. Measure startup
latency against the existing loaders. Fixtures must confirm that managed data,
loaders, logs, and new snapshots contain neither plaintext values nor storage
keys; the explicitly selected private key file is the key-storage exception.

The security claim is limited to stored data under the selected key provider's
boundary. Values still become plaintext in process memory and the environment
because existing applications need them. Encryption cannot protect them from
root or an attacker who can act as the unlocked user. Stronger protection and
universal unattended access require a trusted key source; neither can be promised
merely by changing the file format.
