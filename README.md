## airscand

Linux daemon implementing enough of **WS-Discovery / WS-Scan / WIA** to enable “Scan to Computer” for common network scanners (starting with the Epson WF-3640 MFP).

Currently we only handle a single page image using the platen.

Project status, phase progress, operational checklists, and tested device models / interoperability notes live in [`docs/status.md`](docs/status.md).

### Quick start

Get the daemon running in a few minutes (full walkthrough, prerequisites, and troubleshooting: **[Getting started](docs/getting-started.md)**).

```bash
uv venv
uv sync --extra dev --no-install-project
export WSD_ADVERTISE_ADDR=192.168.1.50   # your host LAN IP seen by the printer
WSD_HOST=0.0.0.0 uv run python main.py
```

### Development

Tests, Ruff, CI behavior, and local MkDocs preview are documented in [`docs/development.md`](docs/development.md).
