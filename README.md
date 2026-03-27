## airscand

Linux daemon implementing enough of **WSD / WS-Scan** to enable “Scan to Computer” for Epson scanners (starting with WF-3640).

Project status, phase progress, and operational checklists live in `docs/status.md`.

### Install dependencies

This project uses **uv** and a project-local virtual environment (`.venv`).

```bash
uv venv
uv sync --extra dev --no-install-project
```

### Run

```bash
WSD_HOST=0.0.0.0 \
WSD_ADVERTISE_ADDR=192.168.1.50 \
uv run python main.py
```


