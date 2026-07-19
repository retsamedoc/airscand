# airscand Status

## Current Project Status

- **Phase 1 (Discovery)** is complete:
  - Periodically multicasts WS-Discovery **Hello** (`wsdp:Device pub:Computer`, `XAddrs` on this host)
  - UDP listener responds to **Probe** with unicast `ProbeMatches` and to **Resolve** with `ResolveMatches` (when the EPR matches this daemon)
  - Dispatch uses `wsa:Action` (not substring matching); `RelatesTo` is correlated to inbound `MessageID`
  - Advertised `XAddrs` can be explicitly set for LAN reachability

- **Phase 2 (HTTP + WS-Eventing registration)** is complete:
  - Outbound WS-Transfer preflight + WS-Eventing **Subscribe** flow is implemented
  - **Lease maintenance:** `SubscribeResponse` is parsed for **Subscription Manager** address, optional **ReferenceParameters** XML, **Identifier**, and **Expires**; values are held on **`Config`** as `scanner_eventing_subscribe_manager_url`, `scanner_eventing_subscribe_manager_reference_parameters_xml`, `scanner_eventing_subscription_id`, and `scanner_eventing_subscribe_expires` (parallel `*_status` fields for the optional **ScannerStatusSummary** subscription). `_eventing_maintenance_loop` in `main.py` wakes before lease expiry (fraction from `WSD_EVENTING_RENEW_AFTER_FRACTION`, with fallbacks for unparsable durations) and calls **`renew_subscription`**. Failed **Renew** or missing deadlines exits maintenance so the registration loop can resubscribe with backoff.
  - **Teardown:** **SIGINT** / **SIGTERM** run **`_unsubscribe_eventing_best_effort`** before task cancellation: **Unsubscribe** targets the stored manager URL and sends **ReferenceParameters** XML from **SubscribeResponse** when the scanner requires them (ScannerStatusSummary subscription first when an id is present, then the primary subscription). This is best-effort (logged failures do not block shutdown).
  - Optional second subscription for **ScannerStatusSummaryEvent** uses parallel `*_status` config fields and the same renew/unsubscribe pattern.
  - Win10-aligned WDP scan subscribe target (`/WDP/SCAN`) is supported by default
  - Daemon registration succeeds against target scanners and host is selectable as a scan destination
  - Outbound **GetStatus** for subscriptions is implemented (`get_subscription_status` in `app/ws_eventing_client.py`) so operators can read device-reported lease without issuing **Renew**; some non-eventing SOAP bodies still use regex helpers (see `docs/ws-eventing_audit.md` §11)
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

- **Phase 5 (compliance / interop hardening) — in progress:**
  - **Why this phase:** strict peers need SOAP-shaped responses, predictable subscription semantics, and operable timeouts/diagnostics—not only “happy path” Epson validation.
  - **Already shipped (inbound, `app/ws_scan.py`):** in-memory **Subscribe** / **Renew** / **GetStatus** / **Unsubscribe** with SOAP faults for validation and unknown/expired ids (**GetStatus** does not extend the lease); unknown or missing **`wsa:Action`** returns **`application/soap+xml`** faults (`wsa:ActionNotSupported` / `wse:InvalidMessage`) per `docs/ws-eventing_audit.md` §1, §4, §9.
  - **Inbound residual (audits / `IMPLEMENTATION_PLAN.md`):** namespace-aware parsing where regex remains risky (`docs/ws-eventing_audit.md` §5, §11). Inbound **Subscribe** accepts optional **EndTo** distinct from **NotifyTo** (for **SubscriptionEnd** delivery) and faults invalid **Expires** when present.
  - **Outbound residual (same audits / plan):** optional assert **RelatesTo** / response **Action** on critical outbound calls (`WSD_VALIDATE_OUTBOUND_SOAP_RESPONSE`); regex-heavy parsing on some WS-Scan bodies. Core path remains: persisted manager EPR + **Renew** + shutdown **Unsubscribe** (Phase 2 above). Outbound SOAP uses separate **connect** vs **read** aiohttp timeouts (see `WSD_SOAP_HTTP_*`, `docs/configuration.md`). Mid-scan **XAddr** rotation after registration is not wired (registration failover only).
  - **SOAP mini-library** (`app/soap/`): shared builders/parsers/transport; orchestration stays in `ws_eventing_client.py` with `main.py` owning registration and lease timing.
  - **Parsing and tests:** contract tests for fault mapping, renew edge cases, and subscription-end semantics (`docs/ROADMAP.md`, `docs/ws-eventing_audit.md` §17).

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
- **`WSD_EVENTING_RENEW_AFTER_FRACTION`**: fraction of the parsed **Expires** duration to wait before sending **Renew** (default `0.9`).
- **`WSD_EVENTING_RENEW_MIN_SLEEP_SEC`**: minimum sleep when a computed renew delay would otherwise be zero (default `5`).
- **`WSD_EVENTING_RENEW_FALLBACK_DURATION_SEC`**: duration in seconds used when **Expires** is missing or unparsable for scheduling (default `3600`).
- **`WSD_EVENTING_SUBSCRIPTION_ID`**: optional override for the primary subscription **Identifier** (rarely needed).
- **`WSD_EVENTING_SUBSCRIPTION_ID_STATUS`**: optional **Identifier** for the secondary **ScannerStatusSummary** subscription.
- **`WSD_HELLO_INTERVAL_SEC`**: seconds between multicast Hello messages (default `60`). Use `0` to send only one Hello at startup.
- **`WSD_METADATA_VERSION`**: value placed in discovery `MetadataVersion` (default `1`)
- **`WSD_APP_SEQUENCE_INSTANCE_ID`**: `InstanceId` on Hello `AppSequence` (default `1`)
- **`WSD_APP_SEQUENCE_SEQUENCE_ID`**: `SequenceId` on Hello `AppSequence` (default: persisted `urn:uuid:...` under `XDG_STATE_HOME`, analogous to `WSD_UUID`)

## Phase 2 Validation Checklist (Complete)

- Start daemon and watch logs for outbound registration attempt/success
- Confirm registration sequence logs: `Outbound WS-Transfer Get sending` -> `Outbound WS-Transfer Get completed` -> `Outbound WS-Eventing subscribe sending`
- After a successful subscribe, confirm logs eventually show `Outbound WS-Eventing renew sending` / `completed` on the expected lease cadence (or check that the scanner keeps delivering events across the original **Expires** window)
- Confirm subscribe destination is `http://<scanner>/WDP/SCAN` (Win10-aligned) unless overridden by `WSD_SCANNER_SUBSCRIBE_TO_URL`
- Confirm scanner shows this host as a scan destination
