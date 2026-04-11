## Cursor Cloud specific instructions

**airscand** is a single-process Python asyncio daemon implementing WSD/WS-Scan for scanner-to-computer functionality. No external services (databases, Docker, etc.) are required.

### Dependencies

Managed by **uv** with `pyproject.toml` / `uv.lock`. The update script runs `uv sync --extra dev --no-install-project` to install runtime + dev deps into a project-local `.venv`.

### Running services

| Service | Command | Notes |
|---|---|---|
| Daemon | `WSD_HOST=0.0.0.0 WSD_ADVERTISE_ADDR=<LAN_IP> uv run python main.py` | Starts WS-Discovery (UDP 3702), HTTP server (TCP 5357), and eventing loop. Without a physical scanner on the LAN, the daemon runs but logs "Scanner endpoint not yet discovered". |
| Tests | `uv run pytest` | All 147 tests are self-contained with mocks; no scanner needed. Coverage enabled by default. |
| Lint | `uv run ruff check .` | Ruff lint with rules F, I, D (Google docstrings). |
| Format check | `uv run ruff format --check .` | Line length 100, Python 3.11+ target. |
| Docs preview | `uv sync --extra docs --no-install-project && uv run mkdocs serve` | Optional MkDocs-material site on port 8000. |

### Non-obvious caveats

- The HTTP endpoint `/wsd` only accepts SOAP POST; a GET returns 405 — this is expected.
- The daemon requires `WSD_ADVERTISE_ADDR` to be a reachable LAN IP for real scanner interaction. In cloud/CI environments, use `127.0.0.1` to exercise startup paths.
- Persistent state (UUID, sequence ID) is stored under `~/.local/state/airscand/` (XDG_STATE_HOME).
- The `--no-install-project` flag is intentional — the project is not an installable package; deps are synced without installing the project itself.
- `uv` must be on PATH. It installs to `~/.local/bin` by default; ensure that directory is in PATH.
