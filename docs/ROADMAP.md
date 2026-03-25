## ROADMAP

### Phase 1 closeout (Discovery) - complete

- WS-Discovery Probe response now returns namespace-correct `ProbeMatches`.
- `wsa:RelatesTo` is correlated to inbound probe `wsa:MessageID`.
- `XAddrs` is built from an explicit advertised address (`WSD_ADVERTISE_ADDR`) with fallbacks.
- Discovery logging now includes sender address, extracted message ID, and advertised `XAddrs`.
- Added automated coverage for ProbeMatch generation and Probe->ProbeMatches responder behavior.

#### Phase 1 env vars used

- `WSD_HOST`: HTTP bind host.
- `WSD_PORT`: HTTP bind port.
- `WSD_ENDPOINT`: WS-Scan SOAP endpoint path.
- `WSD_SCAN_PATH`: scan upload endpoint path.
- `WSD_OUTPUT_DIR`: output directory for uploaded scan files.
- `WSD_UUID`: optional explicit persistent identity UUID.
- `WSD_ADVERTISE_ADDR`: LAN-reachable address/host to publish in `XAddrs`.

#### Known limitations (Phase 2+)

- SOAP parsing remains intentionally lightweight and string-based.
- Discovery responder still only handles the minimal probe path, not full WS-* compliance.
- WS-Scan SOAP actions still use minimal placeholder behavior and need fuller protocol responses.

### Near-term (Phase 1–2 focus)

- Keep the current **single-process** architecture: one asyncio loop running
  - UDP WS-Discovery listener task
  - HTTP server task (currently `aiohttp`)
- Goal: validate that the printer discovers the host and reaches the HTTP endpoint(s) reliably.

### Re-evaluate after Phase 1–2: FastAPI/uvicorn option

If the HTTP surface grows (more SOAP actions, validation, middleware, debug tooling), consider switching the HTTP server from `aiohttp` to **FastAPI + uvicorn**, while still keeping **one asyncio loop** for discovery + HTTP.

#### Why we didn’t do this in Phase 0

- Discovery is a singleton-ish UDP multicast responder; typical web-server scaling (multi-worker) can cause duplicate responses and confusing behavior.
- uvicorn/gunicorn lifecycle + signals are simplest when they own the process; embedding them increases complexity early.
- Phase 0 goal is “starts cleanly” + observability, not framework choice.

#### Decision constraints (when revisiting)

- If using a process manager (gunicorn), ensure **only one** discovery responder exists.
- Prefer **single-worker** HTTP until discovery is split into a separate service/process.
- Ensure graceful shutdown stops both HTTP and discovery cleanly.

