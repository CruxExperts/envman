---
layout: default
title: Installation sources and updates
---

# Installation sources and updates

The public installer is a committed PEP 723 `uv --script` file generated from Envman's standard-library release protocol. It has no third-party runtime dependencies. It downloads `release-manifest.json` from the latest GitHub release, then downloads only the assets named by that manifest.

## Trust boundary

The installer accepts a manifest only when all of these checks pass:

1. The document is bounded, UTF-8 JSON with the exact `envman.release-manifest` schema and schema version.
2. The repository is exactly `CruxExperts/envman`, the version is strict `MAJOR.MINOR.PATCH` SemVer, and each asset URL is the immutable `https://github.com/CruxExperts/envman/releases/download/vVERSION/...` URL for that version.
3. The wheel and `runtime-constraints.txt` assets have bounded sizes, matching SHA-256 digests, matching byte lengths, safe basenames, and the expected filenames.
4. The constraints file contains only exact package pins and includes `cryptography`. The wheel is inspected as a ZIP without extracting untrusted members, and its Envman metadata must match the manifest version.
5. Downloads use HTTPS and accept only GitHub-controlled hosts and redirects. Credentials and fragments are rejected.
6. The host is Linux x86_64 with CPython `>=3.12,<3.13`, and the invoked `uv` reports a version in `>=0.11,<0.12` (use `uv 0.11.21` for Envman 0.1.4).
7. After installation, the command path is resolved from `uv tool dir --bin` and that exact executable must report the manifest version. Verification never falls back to a different `envman` found through `PATH`.

The installer trusts the local `uv` executable and selected Python runtime, GitHub release hosting and its controlled asset redirects, and PyPI over TLS for the exact packages in the verified constraints projection. It does not claim a hermetic dependency install. `--no-build` prevents source builds while installing the verified wheel.

## Receipt-directed updates

After a verified install, the installer creates `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`. A missing state directory is created with mode `0700`; an existing non-symlink directory keeps its current mode. The receipt is written atomically with mode `0600`, refuses symlinks, and has the exact `envman.install-receipt` schema. It records:

- installed version and installation time;
- provider (`github-release-wheel`) and repository;
- manifest URL;
- verified wheel and runtime-constraints asset metadata;
- installer version (`0.1.4` for receipts created by this release's installer) and `uv` versions.

`envman update` reads that receipt and supports only its recorded provider. It fetches the recorded manifest source, rejects a candidate that is older than the recorded version, and reports `current` without reinstalling an equal version. `--check` stops after reporting availability. An update downloads and verifies the new assets, prefetches the prior assets, and writes the new receipt only after the replacement succeeds.

## Failure, rollback, and uninstall

If replacement fails, the installer attempts to uninstall the partially replaced `envman` tool, reinstalls the previously verified wheel and constraints, and restores the previous receipt. If rollback itself fails, it reports both failures rather than claiming success.

There is no `envman uninstall` command. To remove only the `uv` tool, run:

```bash
uv tool uninstall envman
```

That command does not remove managed values, backups, shell-loader files, or the receipt. A deliberately abandoned installation should remove the stale receipt at `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json` before a fresh install; otherwise the installer will reject the mismatch between an existing receipt and an absent Envman tool. See [storage and shell loading](storage-and-shell-loading.md) for the data that remains outside the tool installation.
