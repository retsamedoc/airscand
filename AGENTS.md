# Agent operational notes

Keep this file short. Status and backlog live in `IMPLEMENTATION_PLAN.md`.

## Verify changes

- `uv run ruff check app tests && uv run ruff format app tests`
- `uv run pytest` (full suite; no network required for default tests)

## Run the daemon

See `README.md` and `docs/getting-started.md` for environment variables and `python main.py` / container flows.
