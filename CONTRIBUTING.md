# Contributing

Use [GitHub Issues](https://github.com/CruxExperts/envman/issues) for reproducible defects and feature proposals. Use [GitHub Discussions](https://github.com/CruxExperts/envman/discussions) for questions and open-ended design discussion. Keep changes focused and describe the observable behavior they affect.

## Development setup

Envman targets Python 3.12 and pins its `uv` development workflow:

```bash
uv sync --locked --group dev
```

Install the repository hooks if you want local commit and push checks:

```bash
git config core.hooksPath .githooks
```

## Checks

Run the tests that cover your change. The repository test suite can be run with:

```bash
uv run --locked --no-sync python -m unittest discover -s tests -p 'test_*.py'
```

Do not include credentials, managed environment values, backup passwords, private paths, or machine-specific output in commits, issues, or pull requests. Update public documentation when a user-visible behavior or command changes. Do not hand-edit generated release artifacts; keep their source and generated form consistent.

Use [Conventional Commits](https://www.conventionalcommits.org/) for commit titles. Contributions are released under the [MIT License](LICENSE). Follow the [Code of conduct](CODE_OF_CONDUCT.md).
