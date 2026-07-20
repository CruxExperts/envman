---
layout: default
title: Versioning and releases
---

# Versioning and releases

## Version source and checks

`VERSION` is Envman's only canonical version value. Hatchling reads it for package metadata, and the CLI reads installed distribution metadata with a source-checkout fallback to `VERSION`. Keep the README display synchronized with:

```bash
uv run --locked --no-sync python scripts/version.py sync
uv run --locked --no-sync python scripts/version.py check
```

`sync` changes only the README version display. `check` parses the canonical release protocol and fails unless the README display matches `VERSION` and `INSTALLER_VERSION == VERSION`; all three values must be strict `MAJOR.MINOR.PATCH` versions. This release gate prevents stale installer receipt provenance from shipping.

## Patch-default planning

Plan the next release from the latest matching `vMAJOR.MINOR.PATCH` tag:

```bash
uv run --locked --no-sync python scripts/version.py plan
```

The planner examines active commits after that tag. A complete `Revert` commit and the exact commit it identifies do not contribute to the release. Merge commits and the release-version synchronization commit are ignored. Other non-Conventional subjects are reported as warnings rather than silently treated as release intent.

Every remaining Conventional Commit defaults to a patch bump. A commit body can set explicit intent with one trailer:

```text
Release-Type: major
Release-Type: minor
Release-Type: patch
Release-Type: none
```

The highest explicit or default intent wins across the release batch. A `BREAKING CHANGE:` or `type!:` marker requires an explicit `Release-Type:` trailer; the planner reports a warning when the marker has no explicit intent. Review the JSON result and warnings before changing `VERSION`.

## Tag-gated GitHub workflow

After updating `VERSION`, the README, and the changelog, create a version-matching tag and push it only after the local checks pass:

```bash
git tag v0.1.5 -m "Release v0.1.5"
git push origin v0.1.5
```

The release workflow runs only for tags matching `v[0-9]*`. Its source gate requires the tag name without `v` to equal `VERSION` and the tagged commit to be an ancestor of `origin/main`. It then runs locked tests, `version.py check`, the documentation-index check, and installer rendering parity.

## Build, assets, and publication

The build job sets `SOURCE_DATE_EPOCH` to the tagged commit timestamp, runs `uv build --no-build-isolation` twice, and requires byte-identical wheel and source-archive outputs. `scripts/release_assets.py` writes exact transitive runtime pins from `uv.lock`, one release manifest, and `SHA256SUMS.txt`. The publish job creates a draft GitHub release from the matching `CHANGELOG.md` section, uploads the wheel, source archive, installer, manifest, constraints, and checksum list, attests the release assets, and then clears the draft state.

The canonical release protocol and rendered installer must carry the same `INSTALLER_VERSION` as `VERSION`, so the v0.1.5 installer writes `installer_version: 0.1.5` in every new receipt. The installer and `envman update` verify the manifest, asset URL and hash, wheel metadata, compatibility, and runtime constraints. Installation records a private receipt under `${XDG_STATE_HOME:-$HOME/.local/state}/envman/install.json`; an update requires that receipt and refuses to switch providers or downgrade. A failed replacement attempts a rollback, so inspect the receipt and the installed command before declaring publication complete.
