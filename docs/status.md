# airscand Status

## Current Project Status

- **Phase 1 (Discovery)** is complete:
  - Periodically multicasts WS-Discovery **Hello** (`wsdp:Device pub:Computer`, `XAddrs` on this host)
  - UDP listener responds to **Probe** with unicast `ProbeMatches` and to **Resolve** with `ResolveMatches` (when the EPR matches this daemon)
  - Dispatch uses `wsa:Action` (not substring matching); `RelatesTo` is correlated to inbound `MessageID`
  - Advertised `XAddrs` can be explicitly set for LAN reachability

- **Phase 2 (HTTP + WS-Eventing registration)** is complete:
  - Outbound WS-Transfer preflight + WS-Eventing subscription flow is implemented
  - Win10-aligned WDP scan subscribe target (`/WDP/SCAN`) is supported by default
  - Daemon registration succeeds against target scanners and host is selectable as a scan destination
  - Completion date: **2026-03-26**
  - Tested device models: **Epson WF-3760**, **Epson WF-3640**

- **Phase 3 (WS-Scan basics)** is complete:
  - SOAP endpoint now handles WS-Scan `CreateScanJob` and `ScanAvailableEvent`
  - `ScanAvailableEvent` is acknowledged with a SOAP 1.2 envelope (`Content-Type: application/soap+xml`), `wsa:RelatesTo` matching the notification `wsa:MessageID`, and synthetic `ScanAvailableEventResponse` action (HTTP 200)
  - `ScanAvailableEvent` asynchronously triggers outbound `ValidateScanTicket`, outbound `CreateScanJob`, and outbound `RetrieveImage` against scanner `/WDP/SCAN`
  - `ValidateScanTicketRequest` uses inner **ScanTicket** from **DefaultScanTicket** when the best-effort `GetScannerElements` probe succeeds; otherwise a Win10-like scan ticket template
  - `RetrieveImageRequest` maps `JobId` and `JobToken` from `CreateScanJobResponse`, and `DocumentDescription` to default `1` (destination tokens apply to **CreateScanJob** `DestinationToken` selection, not **RetrieveImage**)
  - Inbound `CreateScanJob` requests return `CreateScanJobResponse` with **JobId**, **JobToken**, **ImageInformation**, and **DocumentFinalParameters**
  - Preserves WS-Addressing request/response correlation via `wsa:RelatesTo`
  - **Epson WF-3640** validated end-to-end on the device-initiated chain (**ScanAvailable** through **RetrieveImage**)
  - Completion date: **2026-03-26**

- **Phase 4 (Image capture core goal)** is complete:
  - `/scan` saves uploads using atomic write semantics
  - Empty payloads are rejected with explicit `400` response
  - Save logs include bytes, content type, and detected file extension
  - Automated tests now cover successful persistence and error paths
  - Device-initiated capture persists images under **`WSD_OUTPUT_DIR`** (default `./scans`) from the outbound **RetrieveImage** / MTOM path when configured for the scan chain
  - **Hardware validation:** **Epson WF-3640** — scan from the printer front panel to this host; image saved under `scans/` with no warnings or failures observed across modules (completion checkpoint: **2026-03-28**)
  - Earlier milestone completion date: **2026-03-26**

- **Next focus (Phase 5):**
  - **SOAP mini-library** (`app/soap/`): shared namespaces, envelope, `SoapHttpClient`, parsers; orchestration stays in `ws_eventing_client.py`
  - Improve SOAP parsing robustness (namespace-aware parsing for more actions; see `docs/ROADMAP.md`)

## Configuration (environment variables)

- **`WSD_HOST`**: bind address (default `0.0.0.0`)
- **`WSD_PORT`**: HTTP port (default `5357`)
- **`WSD_ENDPOINT`**: SOAP endpoint path (default `/wsd`)
- **`WSD_SCAN_PATH`**: upload endpoint path (default `/scan`)
- **`WSD_OUTPUT_DIR`**: directory to write scans (default `./scans`)
- **`WSD_UUID`**: override persistent UUID (optional). If unset, a UUID is generated once and stored under `XDG_STATE_HOME` (or `~/.local/state`).
- **`WSD_ADVERTISE_ADDR`**: address/host advertised in discovery `XAddrs`. Set this to a printer-reachable LAN IP/hostname.
- **`WSD_SCANNER_XADDR`**: optional scanner endpoint override used for outbound WS-Eventing registration. If unset, daemon discovers scanner `XAddrs` via WS-Discovery `ProbeMatches`.
- **`WSD_SCANNER_SUBSCRIBE_TO_URL`**: optional explicit WS-Eventing subscribe target URL. When set, this overrides auto-derived scanner subscribe URL.
- **`WSD_EVENTING_PREFLIGHT_GET`**: controls WS-Transfer preflight (`Get`) before `Subscribe` (default `true`). Set `0`/`false` to disable during troubleshooting.
- **`WSD_EVENTING_NOTIFY_TO_URL`**: optional explicit callback URL used in `wse:EndTo` and `wse:NotifyTo` for outbound `Subscribe`.
- **`WSD_HELLO_INTERVAL_SEC`**: seconds between multicast Hello messages (default `60`). Use `0` to send only one Hello at startup.
- **`WSD_METADATA_VERSION`**: value placed in discovery `MetadataVersion` (default `1`)
- **`WSD_APP_SEQUENCE_INSTANCE_ID`**: `InstanceId` on Hello `AppSequence` (default `1`)
- **`WSD_APP_SEQUENCE_SEQUENCE_ID`**: `SequenceId` on Hello `AppSequence` (default: persisted `urn:uuid:...` under `XDG_STATE_HOME`, analogous to `WSD_UUID`)

## Phase 2 Validation Checklist (Complete)

- Start daemon and watch logs for outbound registration attempt/success
- Confirm registration sequence logs: `Outbound WS-Transfer Get sending` -> `Outbound WS-Transfer Get completed` -> `Outbound WS-Eventing subscribe sending`
- Confirm subscribe destination is `http://<scanner>/WDP/SCAN` (Win10-aligned) unless overridden by `WSD_SCANNER_SUBSCRIBE_TO_URL`
- Confirm scanner shows this host as a scan destination
