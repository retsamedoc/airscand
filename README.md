## airscand

Linux daemon implementing enough of **WSD / WS-Scan** to enable “Scan to Computer” for Epson scanners (starting with WF-3640).

### Phase 0: run locally

This project uses **uv** and a project-local virtual environment (`.venv`).

```bash
uv venv
uv sync --extra dev --no-install-project
uv run python main.py
```

### Run tests

```bash
uv run pytest
```

### Configuration (environment variables)

- **`WSD_HOST`**: bind address (default `0.0.0.0`)
- **`WSD_PORT`**: HTTP port (default `5357`)
- **`WSD_ENDPOINT`**: SOAP endpoint path (default `/wsd`)
- **`WSD_SCAN_PATH`**: upload endpoint path (default `/scan`)
- **`WSD_OUTPUT_DIR`**: directory to write scans (default `./scans`)
- **`WSD_UUID`**: override persistent UUID (optional). If unset, a UUID is generated once and stored under `XDG_STATE_HOME` (or `~/.local/state`).

