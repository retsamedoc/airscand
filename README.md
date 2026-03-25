## airscand

Linux daemon implementing enough of **WSD / WS-Scan** to enable “Scan to Computer” for Epson scanners (starting with WF-3640).

### Current Project Status

- Phase 1 discovery closeout is in place:
  - UDP WS-Discovery listener responds with `ProbeMatches`
  - `RelatesTo` is correlated to inbound `MessageID`
  - advertised `XAddrs` can be explicitly set for LAN reachability
- The daemon can now be run to observe scanner discovery and HTTP contact attempts.
- Current goal is to move beyond initial connectivity and decode Epson-specific WS-Scan quirks (SOAP/action/header details) required for reliable end-to-end scan negotiation.

### Run and observe scanner connection attempts

This project uses **uv** and a project-local virtual environment (`.venv`).

```bash
uv venv
uv sync --extra dev --no-install-project
uv run python main.py
```

With the service running, trigger scanner discovery/scan-to-computer from the printer UI and watch logs for:

- discovery events (`Probe received`, `ProbeMatch sent`)
- advertised `XAddrs` value used by the daemon
- inbound SOAP requests to `/wsd`
- scan upload attempts to `/scan`

Example LAN-oriented run:

```bash
WSD_HOST=0.0.0.0 \
WSD_ADVERTISE_ADDR=192.168.1.50 \
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
- **`WSD_ADVERTISE_ADDR`**: address/host advertised in discovery `XAddrs`. Set this to a printer-reachable LAN IP/hostname.

