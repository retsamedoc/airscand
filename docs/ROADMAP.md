## ROADMAP

### Phase 1 closeout (Discovery) - complete

- WS-Discovery Probe response now returns namespace-correct `ProbeMatches`.
- `wsa:RelatesTo` is correlated to inbound probe `wsa:MessageID`.
- `XAddrs` is built from an explicit advertised address (`WSD_ADVERTISE_ADDR`) with fallbacks.
- Discovery logging now includes sender address, extracted message ID, and advertised `XAddrs`.
- Added automated coverage for ProbeMatch generation and Probe->ProbeMatches responder behavior.
- Important: discovery-only closeout is a preliminary milestone; scanner workflow validation still requires Phase 2 WS-Eventing registration.

### Phase 2 closeout (HTTP + WS-Eventing registration) - complete

- Outbound registration loop now runs WS-Transfer preflight (`Get`) followed by WS-Eventing `Subscribe`.
- Default subscribe target is Win10-aligned WDP scan endpoint on scanner host (`/WDP/SCAN`) with fallback/override controls.
- Subscribe envelope now includes WSD/WDP scan fields needed for Epson interoperability (`From`, `EndTo`, `NotifyTo`, filter, and scan destinations).
- Fault-aware retries remain in place across registration attempts (`wsa:DestinationUnreachable` is logged with structured diagnostics).
- Manual validation: scanner registration succeeds and host can be selected as a scan destination.
- Completion date: **2026-03-26**
- Tested device models: **Epson WF-3640**

### Phase 3 closeout (WS-Scan basics) - complete

- HTTP SOAP handler now supports WS-Scan `CreateScanJob` and `ScanAvailableEvent` in addition to WS-Eventing actions.
- `ScanAvailableEvent` now returns an immediate generic HTTP `200 OK` and triggers asynchronous outbound scanner calls.
- Outbound chain now follows WF-3640 flow: `ValidateScanTicket` (fixed Win10-like template), then `CreateScanJob`, then `RetrieveImage` to scanner `/WDP/SCAN`.
- Outbound chain now also issues best-effort `GetScannerElements` before validation to collect `ScannerDescription`, `DefaultScanTicket`, `ScannerConfiguration`, and `ScannerStatus` for observability.
- `RetrieveImageRequest` now sends `JobId` from `CreateScanJobResponse`, `JobToken` from resolved destination token, and default `DocumentDescription` value `1`.
- Inbound `CreateScanJob` requests return a minimal SOAP `CreateScanJobResponse` with `sca:JobId`.
- WS-Addressing correlation is preserved with `wsa:RelatesTo` mapped from inbound `wsa:MessageID`.
- Added automated coverage for CreateScanJob response generation and end-to-end action dispatch behavior.
- Completion date: **2026-03-26**

### Phase 4 closeout (Image capture core goal) - complete

- `/scan` payload persistence is now hardened with atomic write semantics (temp file + replace).
- Empty upload payloads are rejected with explicit `400` responses.
- Scan save logging now includes byte size, input content type, and detected file extension.
- Added automated coverage for `/scan` success path and error handling (empty payload, invalid config).
- Completion date: **2026-03-26**

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

### Near-term (Phase 5 focus)

- Keep the current **single-process** architecture: one asyncio loop running
  - UDP WS-Discovery listener task
  - HTTP server task (currently `aiohttp`)
- Improve SOAP parsing robustness (namespace-aware parsing for additional actions and richer fault handling).
- Investigate and potentially replace the current logging system with [structlog](https://www.structlog.org/en/stable/index.html) (structured context, flexible rendering, stdlib integration).

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

