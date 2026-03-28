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
  - `ScanAvailableEvent` is acknowledged immediately with generic HTTP `200 OK`
  - `ScanAvailableEvent` asynchronously triggers outbound `ValidateScanTicket`, outbound `CreateScanJob`, and outbound `RetrieveImage` against scanner `/WDP/SCAN`
  - Initial `ValidateScanTicketRequest` uses a fixed Win10-like scan ticket template
  - `RetrieveImageRequest` currently maps `JobId` from `CreateScanJobResponse`, `JobToken` from resolved destination token, and `DocumentDescription` to default `1`
  - Inbound `CreateScanJob` requests return minimal `CreateScanJobResponse` payload with `sca:JobId`
  - Preserves WS-Addressing request/response correlation via `wsa:RelatesTo`
  - Completion date: **2026-03-26**

- **Phase 4 (Image capture core goal)** is complete:
  - `/scan` saves uploads using atomic write semantics
  - Empty payloads are rejected with explicit `400` response
  - Save logs include bytes, content type, and detected file extension
  - Automated tests now cover successful persistence and error paths
  - Completion date: **2026-03-26**

- **Next focus (Phase 5):**
  - Improve SOAP parsing robustness and richer fault handling

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
