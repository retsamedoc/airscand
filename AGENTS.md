# Agents

Keep this file short; backlog and status belong in `IMPLEMENTATION_PLAN.md`.

## Commands

- Tests: `uv run pytest tests/` (default `addopts` in `pyproject.toml` enable coverage; add `--no-cov` for a faster run).
- Lint / format: `uv run ruff check app tests` and `uv run ruff format app tests`.

## Run the daemon

See `README.md` and `docs/getting-started.md` for environment variables and `python main.py` / container flows.
