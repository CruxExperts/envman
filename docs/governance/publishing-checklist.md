---
layout: default
title: Publishing checklist
---

# Publishing checklist

## Public boundary

- [ ] README, LICENSE, SECURITY, CONTRIBUTING, SUPPORT, and Code of Conduct are present and linked.
- [ ] No credentials, personal email, machine paths, hostnames, transcripts, or private maintenance artifacts are tracked.
- [ ] Installation and repository URLs point to `CruxExperts/envman`.

## Build and release

- [ ] `VERSION`, README display, package metadata, and release tag agree.
- [ ] Locked tests, compile checks, generated-installer parity, and documentation-index checks pass.
- [ ] Two clean builds with the same `SOURCE_DATE_EPOCH` are byte-identical.
- [ ] The isolated wheel install reports the expected `envman --version`.
- [ ] Release assets, manifest hashes, and GitHub provenance attestation have been verified.

## GitHub settings

- [ ] Public visibility, issues, discussions, private vulnerability reporting, and Pages workflow deployment are enabled.
- [ ] Immutable releases and a `v*` update/deletion-protected tag ruleset are active.
- [ ] CI, CodeQL, Pages, and release workflows use least privilege and pinned actions.
