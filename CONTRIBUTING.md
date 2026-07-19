# Contributing

Use GitHub Issues for reproducible defects and feature proposals, and GitHub Discussions for questions. Keep pull requests focused, use [Conventional Commits](https://www.conventionalcommits.org/), and include tests for observable behavior changes.

## Local checks

```bash
uv sync --locked --group dev
uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'
uv build --no-build-isolation
```

Install repository hooks after cloning:

```bash
git config core.hooksPath .githooks
```

Contributions are licensed under the [MIT License](LICENSE). Do not commit credentials, local environment files, machine paths, or generated release assets.
