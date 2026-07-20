---
layout: default
title: Publishing checklist
---

# Publishing checklist

Use this checklist for the Envman 0.1.3 release. Every box is intentionally unchecked: local preparation is evidence for the controller, while GitHub and publication steps require an explicit remote review.

## Public boundary

- [ ] `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `SUPPORT.md`, and `CODE_OF_CONDUCT.md` are present, contain no private maintenance material, and link to the intended public repository.
- [ ] A repository search finds no credentials, private keys, personal email addresses, machine-specific paths, hostnames, transcripts, or generated Localsetup state in tracked release content.
- [ ] Installation, issue, discussion, security, and Pages URLs point to `CruxExperts/envman` or its public Pages site.
- [ ] The changelog has a `0.1.3` section with release notes that describe only shipped behavior.

## Local source and documentation checks

- [ ] `VERSION`, the README version display, package metadata, and the intended `v0.1.3` tag agree.
- [ ] `uv sync --locked --group dev` succeeds with the repository's required `uv 0.11.21`.
- [ ] `uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'` passes.
- [ ] `uv run --locked --no-sync python -m py_compile src/envman/*.py scripts/*.py install.py` passes.
- [ ] `uv run --locked --no-sync python scripts/version.py check` passes without a README/VERSION mismatch.
- [ ] `uv run --locked --no-sync python scripts/check_docs.py` passes; every indexed public document exists and is linked exactly once from `docs/INDEX.md`.
- [ ] `uv run --locked --no-sync python scripts/render_installer.py` leaves no diff in `install.py`.

## Reproducible build and installer checks

- [ ] Set `SOURCE_DATE_EPOCH` to the tagged commit timestamp and run `uv build --no-build-isolation` twice into separate directories.
- [ ] Compare the two wheel files and source archives with `cmp`; do not accept a non-identical pair.
- [ ] After copying the wheel, source archive, and `install.py` into `release/`, run `uv run --locked --no-sync python scripts/release_assets.py --output release --version 0.1.3` and inspect `release-manifest.json`, `runtime-constraints.txt`, and `SHA256SUMS.txt`.
- [ ] Verify the release manifest contains only `CruxExperts/envman`, `linux-x86_64`, Python `>=3.12,<3.13`, uv `>=0.11,<0.12`, immutable GitHub asset URLs, and exact SHA-256 and size metadata.
- [ ] Install the wheel in an isolated temporary uv-tool environment whose bin directory is absent from `PATH`, confirm `envman --version` reports `0.1.3` through the executable resolved by `uv tool dir --bin`, and confirm the private receipt records the verified manifest, assets, installer version, and uv version.
- [ ] Exercise `envman update --check` and a verified update using a temporary state root; confirm a missing, malformed, symlinked, or unrecognized receipt fails closed.

## Tag and workflow gates

- [ ] Review the extracted `0.1.3` changelog notes and expected asset set before tagging; the workflow publishes automatically and the resulting release is immutable.
- [ ] Confirm the release commit is reachable from `main`, then create the version-matching tag `v0.1.3` only after all local checks pass.
- [ ] Push `v0.1.3` and confirm the tag-triggered GitHub workflow verifies the tag/VERSION match and `origin/main` ancestry.
- [ ] Confirm the build job completes locked tests, docs checks, installer parity, reproducible builds, release-asset generation, and artifact upload.
- [ ] Confirm the publish job creates a draft from the `0.1.3` changelog section, attaches every intended asset, records build-provenance attestations, and then publishes the release automatically.
- [ ] Verify the immutable public release notes, assets, attestations, download URLs, and manifest hashes from a clean environment before announcing the release.

## GitHub settings

- [ ] Public visibility, issues, discussions, private vulnerability reporting, and Pages deployment are enabled and reviewed.
- [ ] Immutable releases and a protected `v*` tag ruleset prevent unauthorized updates or deletions.
- [ ] CI, CodeQL, Pages, and release workflows retain least-privilege permissions and pinned action references.
