# Changelog

All notable changes are documented here.

## [0.1.5] - 2026-07-20

### Fixed

- Add a release-check invariant that parses the canonical release protocol and rejects a stale installer provenance version unless `INSTALLER_VERSION == VERSION`.

## [0.1.4] - 2026-07-20

### Fixed

- Correct installer receipt provenance so receipts created by the changed installer record `installer_version: 0.1.4`.

## [0.1.3] - 2026-07-20

### Fixed

- Resolve the installed command through `uv tool dir --bin` before version verification, preventing a valid installation from being rolled back when the uv tool directory is absent from `PATH`.

## [0.1.2] - 2026-07-20

### Changed

- Redesign the terminal catalog as a full-height, index-free list.
- Replace numeric row shortcuts with Space-based multi-selection and grouped copy, delete, and encrypted-backup actions.
- Classify standalone and underscore-delimited `KEY` names as secrets while excluding `_API_KEY_ENV` references; apply length-aware masking (`4+4` for values 16 or more characters, `2+2` for 10-15, and `1+1` for 6-9) and reject secret values shorter than six characters.

### Fixed

- Clear the prompt row before every redraw so edited values cannot overlap stale text.
- Preserve Git unit and record separators while normalizing command output so an unreleased `feat:` commit receives the patch-default release plan.

## [0.1.1] - 2026-07-19

### Fixed

- Permit GitHub's signed release-asset redirects while preserving the trusted source and redirect-host boundary.

## [0.1.0] - 2026-07-19

### Added

- Terminal UI and scriptable CLI for persistent per-user environment variables.
- Validation and masking for names, URLs, paths, credentials, and sensitive values.
- Encrypted backup export and import.
- Verified GitHub-release installer and receipt-directed updater.
