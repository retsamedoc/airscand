## ROADMAP

This roadmap tracks **remaining** work by timeline and references detailed context in:
- [`docs/wia_client_audit.md`](wia_client_audit.md)
- [`docs/ws-scan_audit.md`](ws-scan_audit.md)
- [`docs/ws-eventing_audit.md`](ws-eventing_audit.md)

### Near-term

- **WS-Eventing — split by role (see `ws-eventing_audit.md`):**
  - **Inbound (this host as subscription manager + sink):** MVP **Subscribe** / **Renew** / **GetStatus** / **Unsubscribe** with in-memory state and SOAP faults is implemented (`app/ws_scan.py`, `app/inbound_eventing_registry.py`). **Subscribe:** optional **EndTo** may differ from **NotifyTo**; invalid **Expires** faults; inbound **`SubscriptionEnd`** emission on lease lapse and sink receive (§3). **Residual:** fuller **EndTo** / **Expires** negotiation matrix (§5–§8); namespace-aware parsing on non-eventing bodies (§11).
  - **Outbound (this host as subscriber to the scanner):** **SubscribeResponse** → persisted manager URL + reference parameters + **Expires**; **`_eventing_maintenance_loop`** → **`renew_subscription`**; shutdown / failed-renew **`_unsubscribe_eventing_best_effort`**; diagnostic **`get_subscription_status`**. **Residual:** optional response **RelatesTo** / **Action** checks (`WSD_VALIDATE_OUTBOUND_SOAP_RESPONSE`); regex on some WS-Scan bodies (§11).
- **SOAP sink / unknown actions:** unsupported **`wsa:Action`** on `/wsd` returns SOAP faults (**resolved**; `ws-eventing_audit` §9).
- **Transport timeout split**: **Shipped** — `SoapHttpClient` uses aiohttp `sock_connect` / `sock_read` from `WSD_SOAP_HTTP_CONNECT_TIMEOUT_SEC` and optional `WSD_SOAP_HTTP_READ_TIMEOUT_SEC` (see `docs/configuration.md`, `docs/wia_client_audit.md` §3). Optional: integration test with a server that stalls the body past the read bound.
- **Roadmap/documentation hygiene**: keep implementation locations (`app/soap/*`, `ws_eventing_client.py`, `main.py`, `ws_scan.py`) reflected in architecture/design/status and audit cross-links.

### Mid-term

- **WIA operation hardening**:
  - Multi-XAddr failover for **eventing registration** is implemented (`discover_scanner_xaddrs`, `main._eventing_registration_loop`); mid-scan SOAP rotation (`scanner_xaddr_failover.py` + `config.scanner_xaddrs`) is still open.
  - Explicit idempotent retry policy for SOAP operations (RetrieveImage bounded retry is **done** — `WSD_RETRIEVE_IMAGE_MAX_RETRIES`).
  See `wia_client_audit` high/medium checklist.
- **WS-Scan follow-through**:
  - Confirm/adjust Probe `Types` interop choice where needed.
  - Cache `GetScannerElements` where safe across subscriptions/events.
  See `wia_client_audit` low/clarify items and `ws-scan_audit` remaining medium/low issues.
- **Eventing parsing robustness**: expand namespace-aware XML handling on critical eventing paths beyond regex parsing.
  See `ws-eventing_audit` medium item (§11).
- **Compliance-oriented tests**: expand contract coverage beyond shipped modules (`tests/test_ws_eventing_audit_compliance.py`, `tests/test_ws_scan_audit_compliance.py`) for remaining fault/lifecycle matrix edge cases.
  See `ws-eventing_audit` low item (§17).
- **WS-Scan handler hardening details**: add missing guardrails noted in audit deltas (e.g., handler assumptions) and document intentional deviations.
  See `ws-scan_audit` remaining low items.

### Far-term

- **CancelJob on shutdown / user abort** (RetrieveImage failure path is **done** — `cancel_scan_job` after exhausted retries when `cancel_job_on_retrieve_error=True`).
  See `wia_client_audit` §7.5 / §8.
- **Vendor profile growth**: extend `app/quirks` and `docs/protocol/vendor_quirks.md` as more hardware is validated.

### Future

- **Security and metadata posture**:
  - Document and/or implement stronger eventing subscription protections (beyond trusted-LAN assumptions in [`SECURITY.md`](../SECURITY.md)).
  - Clarify metadata/WSDL strategy if full standards alignment becomes a goal.
  See `ws-eventing_audit` low items.
- **Logging architecture**: evaluate whether moving to [`structlog`](https://www.structlog.org/en/stable/index.html) materially improves operations.

## Done

- **Platform/server decision**: keep `aiohttp`; `uvicorn/gunicorn` path is closed (not planned).
- SOAP mini-library introduced under `app/soap/` (namespaces, addressing, envelope, fault, transport, parsers).
- `ws_eventing_client` thinned to orchestration + compatibility re-exports.
- Discovery and ws-scan paths updated to consume shared SOAP helpers.
- Shared `ClientSession` reuse is in place via `SoapHttpClient`.
- GetJobStatus polling and RetrieveImage gating are implemented when profile-enabled.
- `app/soap/xmlutil.py` starter hooks and tests are in place for phase-2 XML work.
- Documentation refresh completed for architecture/design/status/README and audit path references.
- Phase 1-4 implementation milestones and Epson WF-3640 validation completed.
- Outbound WS-Eventing lease management: persisted subscription manager URL and reference parameters, parsed `Expires`, `_eventing_maintenance_loop` with `renew_subscription`, and best-effort `unsubscribe_from_scanner` on shutdown / failed renew (`main.py`, `app/ws_eventing_client.py`, `app/config.py`, `app/soap/parsers/eventing.py`).
- Inbound WS-Eventing subscription manager + sink SOAP faults for lifecycle, validation, and unknown `wsa:Action` (`app/ws_scan.py`, `app/inbound_eventing_registry.py`, `app/soap/builders/faults.py`).
- Outbound SOAP HTTP **connect** vs **read** timeouts (`SoapHttpClient` / `aiohttp.ClientTimeout`, `WSD_SOAP_HTTP_*`, `main.configure_soap_http_client_from_config`).
- Explicit scan lifecycle state machine (`app/scan_lifecycle.py`) with guarded transitions and chain result fields (`lifecycle_state`, `lifecycle_path`, …) in `run_scan_available_chain`.
- Outbound WS-Eventing **GetStatus** client (`get_subscription_status`) for lease diagnostics without **Renew**.
- **CancelJob** after exhausted **RetrieveImage** retries on timeout/transport failure; **RetrieveImage** bounded retry via `WSD_RETRIEVE_IMAGE_MAX_RETRIES`.
- Inbound **`SubscriptionEnd`** manager emission + sink handling (`app/inbound_subscription_end_delivery.py`, `tests/test_subscription_end.py`).
- SOAP fault **Detail** extraction in `parse_soap_fault` / `soap_fault_log_fields` for operator diagnostics.

### Historical completion details

- WS-Discovery Probe/Resolve response correctness and correlation.
- WS-Eventing: discovery-driven registration with preflight `Get`, `Subscribe` retries, outbound `Renew` scheduling (`_eventing_maintenance_loop`), and best-effort `Unsubscribe` on shutdown / failed renew.
- WS-Scan device-initiated chain (`ValidateScanTicket -> CreateScanJob -> RetrieveImage`) and metadata probe flow.
- `/scan` persistence hardening (atomic writes, empty payload rejection, improved logging, tests).

