# Changelog

All notable changes are documented here.

## [Unreleased]

### Changed

- Let terminal catalogs use the available height and replace numeric row shortcuts with Space-based multi-selection for copy, delete, and encrypted backup actions.
- Mask standalone and underscore-delimited `KEY` variables with length-aware visible edges, and reject secret values shorter than six characters.

### Fixed

- Clear the prompt line before redrawing edited values so shorter text no longer overlaps stale content.

## [0.1.1] - 2026-07-19

### Fixed

- Permit GitHub's signed release-asset redirects while preserving the trusted source and redirect-host boundary.

## [0.1.0] - 2026-07-19

### Added

- Terminal UI and scriptable CLI for persistent per-user environment variables.
- Validation and masking for names, URLs, paths, credentials, and sensitive values.
- Encrypted backup export and import.
- Verified GitHub-release installer and receipt-directed updater.
