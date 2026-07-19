# Agent Instructions

This repo uses the universal agent repo shape.

## Shared Context

- Root `AGENTS.md` is the shared repo context for Codex, OMP, OpenCode, Cursor, and compatible agents.
- Reusable shared repo skills live under `.agents/skills/<skill>/SKILL.md` only when intentionally selected.
- Platform-specific overrides stay in platform-native files. Do not create repo-private OMP or Cursor configuration without an explicit repo override.

## Repo Profile

- Purpose: Portable terminal environment-variable manager
- Audience: Repository maintainers and agent collaborators
- Stack: python
- Package manager: uv

## Commands

- Test: `uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'`
- Build: `uv build --no-build-isolation`
- Deploy: `Release through the tag-gated GitHub Actions workflow`

## Skill Trust

External skills are not trusted from declarations alone. Install external skills only after fetch, vetting, normalization, sandbox testing when needed, lock update, and authorization roster update.
