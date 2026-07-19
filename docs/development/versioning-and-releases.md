---
layout: default
title: Versioning and releases
---

# Versioning and releases

`VERSION` is Envman's only canonical version value. Hatchling reads it during builds, and the CLI reads installed distribution metadata with a source-checkout fallback to `VERSION`.

Initial release is `0.1.0`. Afterwards, regular batches of non-reverted Conventional Commits default to a patch release. Add `Release-Type: major`, `minor`, `patch`, or `none` in a commit body to state non-default intent. A `BREAKING CHANGE:` marker or `type!:` requires an explicit `Release-Type:` trailer.

Release automation accepts only an annotated `vMAJOR.MINOR.PATCH` tag on an accepted commit reachable from `main`. It verifies the tag/version match, rebuilds twice, installs the wheel in isolation, publishes fixed assets and a manifest, emits GitHub build provenance, and then finalizes the immutable release.
