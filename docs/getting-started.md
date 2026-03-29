# Getting started

This section gets **airscand** running so your scanner can discover this host and send scans to disk.

## Prerequisites

- **Linux** on the machine that will receive scans (the same subnet as the printer is typical).
- **Python** tooling via **[uv](https://github.com/astral-sh/uv)** (see the project `README` for the exact `uv sync` invocation).
- **Network:** Multicast UDP (WS-Discovery) and TCP to your chosen HTTP port (default **5357**) must not be blocked between printer and host.

## Quick start

1. **Clone the repository** and create the virtual environment:

   ```bash
   cd airscand
   uv venv
   uv sync --extra dev --no-install-project
   ```

2. **Set the advertised address** so the printer reaches this computer. Replace the example IP with your host’s LAN address (the one the printer would use to open a web page to this machine):

   ```bash
   export WSD_ADVERTISE_ADDR=192.168.1.50
   ```

   If you omit `WSD_ADVERTISE_ADDR`, the daemon tries to infer a sensible LAN IP; setting it explicitly avoids wrong guesses on multi-homed systems.

3. **Run the daemon:**

   ```bash
   WSD_HOST=0.0.0.0 \
   WSD_ADVERTISE_ADDR=192.168.1.50 \
   uv run python main.py
   ```

4. **Watch the logs** for successful scanner registration (WS-Transfer preflight and WS-Eventing subscribe). Then on the printer, select **Scan to Computer** (or equivalent) and choose this host if it appears.

5. **Find saved files** under `./scans` by default, or whatever you set with `WSD_OUTPUT_DIR`—see [Configuration](configuration.md).

## systemd (optional)

For a long-running service, wrap the same command in a `systemd` unit: set `Environment=WSD_ADVERTISE_ADDR=…` (and other variables), run `uv run python main.py` with `WorkingDirectory` pointing at the project, and ensure the service user can write to `WSD_OUTPUT_DIR`.

## Next steps

- Tune paths, timeouts, and scanner profiles: [Configuration](configuration.md).
- If the host does not appear or scans fail: [Troubleshooting](troubleshooting.md).
