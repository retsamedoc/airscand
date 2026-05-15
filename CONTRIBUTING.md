# Contributing to airscand

Thank you for helping improve the WSD / WS-Scan daemon. This document is the **single entry point** for how to build, test, and submit changes. Deeper protocol context lives under [`docs/`](docs/); the living backlog is [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## Scope and expectations

- **Primary goal:** reliable “Scan to Computer” on Linux for supported network scanners (see [`docs/status.md`](docs/status.md)).
- **Prefer extending** [`app/soap/`](app/soap/) and focused modules over duplicating SOAP helpers in orchestration code.
- **No placeholders:** incomplete stubs create duplicate work; land behavior with tests when you touch a protocol path.
- **Single sources of truth:** avoid adapter layers that mirror the same spec in two places; update docs and code together when behavior changes.

## Development setup

Use **[uv](https://github.com/astral-sh/uv)** and Python **3.11+**:

```bash
uv venv
uv sync --extra dev --no-install-project
```

Optional MkDocs preview:

```bash
uv sync --extra dev --extra docs --no-install-project
uv run mkdocs serve
```

See [`docs/development.md`](docs/development.md) for CI behavior and documentation builds.

## Tests

All tests live under `tests/` and use **pytest** (not `unittest`).

```bash
uv run pytest
```

Coverage is on by default (`pyproject.toml` `addopts`). Faster iteration:

```bash
uv run pytest --no-cov
```

**Why tests matter here:** SOAP and WS-Eventing paths are brittle across vendor quirks; regressions often show up only as wrong subscription correlation, silent lease expiry, or persisted corrupt images. Add or extend tests when you change protocol handling, config defaults, or fault mapping.

## Lint and format

```bash
uv run ruff check app tests
uv run ruff format app tests
```

Apply formatting before pushing:

```bash
uv run ruff format .
```

## Commit messages

Subject lines must follow **[Conventional Commits](https://www.conventionalcommits.org/)**:

```text
<type>[(optional scope)][!]: <description>
```

Examples: `feat(discovery): advertise scanner over WSD`, `fix(ws-scan): close TCP on cancel`, `test: add inbound Subscribe faults`.

Enable the repo hook (optional but recommended):

```bash
git config core.hooksPath .githooks
```

Merge commits, reverts, and `fixup!` / `squash!` subjects are exempt (see `.githooks/commit-msg`).

## Pull requests

1. Run **pytest** and **ruff** locally (CI runs Ruff on PRs; tests run on push to `main` via `.github/workflows/validate.yaml`).
2. Update **protocol or operator docs** in `docs/` when behavior, env vars, or failure modes change.
3. Keep **`IMPLEMENTATION_PLAN.md`** accurate if you close or discover backlog items (status belongs there, not in `AGENTS.md`).
4. Describe **why** the change is needed and note any **interop** or **trusted-LAN** assumptions (see [`SECURITY.md`](SECURITY.md)).

## Coding conventions

- Type hints and Google-style docstrings on **new or heavily edited** public APIs.
- Imports: standard library, third-party, local (`app.*`).
- Configuration via **environment variables** (documented in [`docs/configuration.md`](docs/configuration.md)).

Agent-oriented command cheatsheet: [`AGENTS.md`](AGENTS.md) (keep it operational only).

## Questions

Open a [GitHub issue](https://github.com/retsamedoc/airscand/issues) for bugs or design discussion. For security-sensitive reports, use the process in [`SECURITY.md`](SECURITY.md)—do not file public issues for exploitable vulnerabilities.
