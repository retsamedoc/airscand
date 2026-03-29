# Development

How to run tests and linters locally, what continuous integration runs, and how to build the documentation site. For coding conventions (typing, pytest, docstrings), see the project’s Python rules in the repository (`.cursor/rules/code/python.mdc`).

## Environment

Use **[uv](https://github.com/astral-sh/uv)** and install **dev** dependencies (pytest, ruff, coverage):

```bash
uv venv
uv sync --extra dev --no-install-project
```

Optional: add the **docs** extra to preview the MkDocs site locally:

```bash
uv sync --extra dev --extra docs --no-install-project
```

## Tests

Tests live under `tests/` and use **pytest** with **pytest-asyncio** (see `pyproject.toml`).

```bash
uv run pytest
```

Coverage is enabled by default via `addopts` (`--cov=app --cov-report=term-missing`). To run without coverage:

```bash
uv run pytest --no-cov
```

## Lint and format

The project uses **Ruff** for lint (`F`, `I`, `D` with pydocstyle **Google** convention; missing public docstrings are not enforced on legacy code—see `pyproject.toml`) and format checks (line length 100, Python 3.11+).

```bash
uv run ruff check .
uv run ruff format --check .
```

Apply formatting:

```bash
uv run ruff format .
```

## Continuous integration

**Quality** (`.github/workflows/quality.yaml`) runs on pushes and pull requests that touch Python sources: **Ruff check** and **Ruff format check** on Python 3.11. It does **not** run pytest; run tests locally before merging.

**Docs** (`.github/workflows/docs.yaml`) builds the MkDocs site when documentation or related paths change.

## Documentation site locally

With the `docs` optional dependency installed:

```bash
uv run mkdocs serve
```

Open the served URL (usually `http://127.0.0.1:8000`) to preview. For a one-off build:

```bash
uv run mkdocs build
```

Configuration is in `mkdocs.yaml` at the repository root.
