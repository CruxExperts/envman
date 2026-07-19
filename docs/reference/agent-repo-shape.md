# Agent Repo Shape

This repo follows the `universal-agent-repo` profile.

## Default Shape

- `AGENTS.md` holds shared repo instructions.
- `agent-repo-shape.json` declares enabled agent clients, shared skill surface, platform overrides, and external skill requests.
- `.agents/skills/` is the shared repo-local skill surface when repo skills are selected.
- `.codex/*` is reserved for Codex-specific config, agents, rules, and hooks.
- `.omp/*` is reserved for explicit OMP-specific overrides; the lean default creates none.
- `opencode.json` and `.opencode/*` are reserved for OpenCode-specific config, agents, plugins, tools, and OpenCode-only skills.
- `.cursor/*` is reserved for explicit Cursor-specific overrides; the lean default creates none.
- `.codex/runs/` is local runtime state and is ignored through `.git/info/exclude`.

## External Skills

External skills must be resolved into `external_skills.lock.json` before agents trust them. A trusted lock entry records the resolved source ref, installed path, normalized `SKILL.md` SHA-256, normalized tree SHA-256, import timestamp, and vetting result.

Current external skill requests: none.

## OpenCode Replication

Full OpenCode home configuration replication is not part of the lean default shape. Use the explicit `opencode-replica` export profile only when the goal is to package sanitized global OpenCode configuration for another machine.
