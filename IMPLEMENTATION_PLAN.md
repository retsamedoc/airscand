# Implementation plan (MVP and near-term)

This file is the **living backlog** for airscand. Items are **priority-ordered** (highest first). Each task lists **verification outcomes** (what tests or checks should prove success), not implementation detail.

**Repository facts (confirmed):**

- Application code lives under **`app/`** and **`main.py`** (there is no `src/` tree).
- Shared SOAP/utilities live under **`app/soap/`** and focused modules (`app/mtom.py`, `app/scan_storage.py`, …). There is **`app/lib/`** — treat `app/soap/` as the shared “standard library” for SOAP; prefer extending it over duplicating helpers in orchestration modules.
- **`specs/`** is empty; normative protocol text already exists under **`docs/protocol/`** and **`docs/design.md`**. Optional hygiene: add `specs/README.md` that points to those paths so tooling and contributors have one entry point.

---

## Verified complete (do not re-plan implementation without new requirements)

- **WS-Discovery** server + client probe; **Hello** / **Bye**; correlation patterns (see `docs/architecture.md`, `tests/test_discovery.py`).
- **Outbound WS-Eventing**: **Subscribe**, **Unsubscribe** to stored manager EPR; **Renew** on a lease fraction timer; dual subscriptions (ScanAvailable + ScannerStatusSummary) with separate manager fields (`main.py`, `app/ws_eventing_client.py`, `tests/test_ws_eventing_client.py`, `tests/test_main_registration.py`).
- **SubscribeResponse** parsing: identifier, expires, subscription manager address + reference parameters XML, destination token map (`app/soap/parsers/eventing.py`, ElementTree).
- **Device-initiated scan chain**: **ScanAvailableEvent** SOAP ack, **ValidateScanTicket** → **CreateScanJob** → optional **GetJobStatus** → optional **RetrieveImage** / MTOM (pull) or **push_only** handoff without **RetrieveImage**, coordination with **ScannerStatusSummaryEvent** (`app/ws_scan.py`, `app/ws_eventing_client.py`, `app/quirks/__init__.py`, `app/config.py`, audits).
- **Pull vs push image delivery:** ``ScannerProfile.image_delivery_mode`` (`pull` default), profile **`push_only`**, env **`WSD_IMAGE_DELIVERY_MODE`** override; chain logs ``retrieve_status=SkippedPushOnly`` and does not call **RetrieveImage** when push-only; persistence remains **POST** ``WSD_SCAN_PATH`` + ``save_scan_file`` (`tests/test_ws_eventing_client.py`, `tests/test_quirks.py`, `tests/test_config.py`, `docs/configuration.md`, `docs/ws-scan_audit.md` §11). *Residual:* auto-detect from **ImageTransfer** in **ScannerCapabilities** XML not implemented.
- **Push path** `/scan`: atomic save, empty body rejection (`app/scan_receiver.py`, `app/scan_storage.py`, tests).
- **Inbound WS-Eventing subscription manager** (`app/ws_scan.py`, `app/inbound_eventing_registry.py`, `app/soap/parsers/inbound_eventing.py`, `app/soap/builders/faults.py`, `app/soap/envelope.py`): **Subscribe** allocates stable **Identifier** + granted **Expires**; **Renew** extends lease; **GetStatus** returns stored expiration without mutating lease; **Unsubscribe** removes state; unknown/expired ids and validation failures return **SOAP 1.2 faults** (`tests/test_ws_scan.py`).
- **Unknown or missing `wsa:Action` on `/wsd`:** SOAP 1.2 fault responses (`wsa:ActionNotSupported` / `wse:InvalidMessage`) with `application/soap+xml`, structured logs (`soap_action`, `wsa_message_id`); no `text/plain` success for those POSTs (`tests/test_ws_scan.py`).

- **Documentation reconciliation (status, ROADMAP, architecture, audits):** `docs/status.md` Phase 5 distinguishes **inbound shipped vs residual** and **outbound residual** (why: avoids duplicating work on already-landed SOAP paths); `docs/ROADMAP.md` near-term matches; `docs/architecture.md` package map matches `app/soap/` layout; `docs/ws-eventing_audit.md` defines outbound vs inbound terminology at top.
- **Outbound SOAP HTTP timeouts:** `SoapHttpClient` uses aiohttp `ClientTimeout(sock_connect=…, sock_read=…)`; `WSD_SOAP_HTTP_CONNECT_TIMEOUT_SEC` (default **10**) and optional `WSD_SOAP_HTTP_READ_TIMEOUT_SEC` (global read override); `main.configure_soap_http_client_from_config` after `Config()` (`tests/test_soap_transport.py`, `tests/test_config.py`).
- **Inbound Subscribe validation (MVP):** optional **`wse:EndTo`** requires non-empty **`wsa:Address`** when **`EndTo`** is present; **`EndTo`** may differ from **`NotifyTo`** because manager-emitted **`SubscriptionEnd`** is POSTed to **`EndTo`** (or **`NotifyTo`** when **`EndTo`** is omitted). Non-empty invalid **`wse:Expires`** → **`InvalidExpirationTime`**; filter/delivery faults unchanged (`app/soap/parsers/inbound_eventing.py`, `tests/test_inbound_eventing.py`, `tests/test_ws_scan.py`).
- **`SubscriptionEnd` (WS-Eventing, inbound roles):** When a managed lease expires without **Renew**, or **Unsubscribe**/**Renew**/**GetStatus** hits an already-expired id, the manager queues **`SubscriptionEnd`** (SOAP **`SubscriptionEnd`** action, **Status** URI `SourceCancelling`) to the stored subscriber EPR; **`main._inbound_subscription_lease_sweep_loop`** also expires idle leases every 5s. The sink accepts inbound **`SubscriptionEnd`** notifications and returns **`SubscriptionEndResponse`** (`app/inbound_eventing_registry.py`, `app/inbound_subscription_end_delivery.py`, `app/soap/builders/eventing.py`, `app/soap/namespaces.py`, `app/soap/parsers/subscription_end.py`, `app/ws_scan.py`, `main.py`, `tests/test_subscription_end.py`, `tests/test_ws_scan.py`). *Why tests matter:* without them, lease teardown silently breaks peers that rely on **EndTo** correlation or expect SOAP (not bare HTTP) for teardown.
- **Multi-XAddr registration failover:** [`discover_scanner_xaddrs`](app/discovery.py) returns the full **ProbeMatches** list in order; [`main._eventing_registration_loop`](main.py) tries each candidate and advances on transport-layer failures classified by [`is_scanner_xaddr_transport_failover`](app/soap/transport.py) (`asyncio.TimeoutError`, `ClientConnectorError`, `ClientOSError`). Logs include `xaddr_attempt_index`, `xaddr_candidates_total`, and `scanner_xaddr` per attempt (`tests/test_discovery.py`, `tests/test_main_registration.py`, `tests/test_soap_transport.py`). *Residual:* per-scan outbound legs after registration still target `config.scanner_xaddr` only (no mid-chain rotation).

- **Outbound SOAP response validation (RelatesTo / Action):** Optional strict checks for **Subscribe**, **ValidateScanTicket**, **CreateScanJob**, **GetJobStatus** (when polling), and **RetrieveImage** (SOAP envelope from MTOM) via ``WSD_VALIDATE_OUTBOUND_SOAP_RESPONSE`` / ``Config.validate_outbound_soap_response`` (`app/soap/outbound_response_validation.py`, `app/ws_eventing_client.py`, `main.py`, `app/ws_scan.py`). Default **off** for interop with devices that omit headers (`docs/protocol/vendor_quirks.md`). *Why tests matter:* wrong correlation otherwise accepts mis-attributed HTTP replies as if they matched the in-flight SOAP leg.
- **RetrieveImage payload integrity (pull / MTOM):** When HTTP provides ``Content-Length``, downloaded byte length must match. For ``multipart/related``, checks include closing boundary, optional per-part ``Content-Length``, **xop:Include** → binary part resolution, non-empty payload, and JPEG/PNG/TIFF/PDF magic vs declared MIME. Failures log structured ``integrity_reason_codes`` / lengths and return fault ``airscand:RetrieveImagePayloadIntegrity`` without persisting (`app/mtom.py`, `app/soap/transport.py`, `app/ws_eventing_client.py`, `tests/test_mtom.py`, `tests/test_soap_transport.py`). *Residual:* bounded automatic **RetrieveImage** retry after truncation is not implemented (operators see explicit failure).
- **Namespace-aware SOAP on eventing / WS-A / fault hot paths:** ElementTree with explicit namespace URIs replaces regex for **SubscribeResponse** / **RenewResponse** parsing, subscription manager EPR, reference-parameter id resolution, WS-A **Action** / **MessageID** / **RelatesTo** / **To**, SOAP **Fault** code/subcode/reason, inbound management header id, outbound log correlation, and **ClientContext** / **DestinationToken** extraction (`app/soap/xmlutil.py`, `app/soap/parsers/eventing.py`, `app/soap/addressing.py`, `app/soap/fault.py`, `app/soap/parsers/discovery.py`, `app/soap/transport.py`, `app/soap/parsers/inbound_eventing.py`, `app/soap/parsers/scan.py`). *Why tests matter:* prefix permutations and nested duplicate **Identifier** elements otherwise yield wrong subscription correlation. Regression: `tests/test_eventing_namespace_xml.py`. *Residual:* some WS-Scan body parsers and WS-Discovery **XAddrs** extraction still use regex where audits did not require this increment.

- **`handle_wsd` defensive config wiring (`docs/ws-scan_audit.md` Low §16):** Missing or non-`Config` `app["config"]` returns HTTP **500** with plain text (aligned with `handle_scan`), logs an error, and does not touch `config` fields (`app/ws_scan.py`, `tests/test_ws_scan.py`). *Why tests matter:* a mis-wired aiohttp app previously raised `AttributeError` on the first subscription-manager leg.
- **Fault Detail extraction (`docs/ws-scan_audit.md` Low §15):** `parse_soap_fault` surfaces `fault_detail` (serialised `Detail` children, truncated at 4 096 chars) and `soap_fault_log_fields` exposes it in `logging extra=` dicts; `SoapHttpClient.post_text` / `post_retrieve_image` log it on failure (`app/soap/fault.py`, `app/soap/transport.py`).
- **CancelJob (WIA §7.5):** `cancel_scan_job` sends a WS-Scan **CancelJob** SOAP request on demand; `run_scan_available_chain` calls it automatically on **RetrieveImage** timeout or transport error when `cancel_job_on_retrieve_error=True` (default). Devices that ignore cancel are tolerated — failure is logged, not raised. Action constants `ACTION_CANCEL_JOB` / `ACTION_CANCEL_JOB_RESPONSE` added to `app/soap/namespaces.py`; builder `build_cancel_job_request` added to `app/soap/parsers/scan.py` (`tests/test_ws_eventing_client.py` — 6 new tests).
- **Outbound WS-Eventing GetStatus:** `get_subscription_status`, `build_get_status_request`, `parse_get_status_response` (`app/soap/builders/eventing.py`, `app/soap/parsers/eventing.py`, `app/ws_eventing_client.py`, `tests/test_ws_eventing_client.py`, `tests/test_ws_eventing_audit_compliance.py`). *Why tests matter:* operators can verify device-reported lease without issuing **Renew**; audit §12 outbound residual closed.

---

## Backlog (incomplete) — by priority

### 4. Contract / compliance test suite expansion (`docs/ws-eventing_audit.md` §17)

**Progress:** `tests/test_ws_eventing_audit_compliance.py` maps audit §17 themes by name for both inbound manager and outbound subscriber roles:

- **§1 lifecycle:** happy path Subscribe → Renew → GetStatus → Unsubscribe; **Renew** after monotonic lease expiry → **UnableToRenew** (registry clock only, no asyncio maintenance mocks).
- **§4 / §11 faults:** parametrized **parse_soap_fault** peer subcode matrix; inbound **NotifyTo** empty, **GetStatus** / **Unsubscribe** unknown id, **Renew** `wsa:To` mismatch, unknown **Action** → **ActionNotSupported**.
- **§5–§8 Subscribe validation:** **InvalidExpirationTime**, **DeliveryModeRequestedUnavailable** (non-Push), **FilteringNotSupported** (filter present).
- **§2 outbound:** primary **Renew** SOAP fault → **Unsubscribe** best-effort; dual-subscription **Renew** failure unsubscribes **ScannerStatusSummary** then primary; registration loop backoff (`2s`) + second full **Subscribe** pair after maintenance exit (patched `main.asyncio.sleep` in one test; real maintenance + real 2s backoff in `test_audit_ws_eventing_17_registration_real_maintenance_resubscribe_no_sleep_patch`); outbound **GetStatus** client (`get_subscription_status`, `build_get_status_request`, `parse_get_status_response`).
- **§12 inbound:** expired lease on **GetStatus** → **UnableToRenew**; **GetStatus** does not extend lease (monotonic clock, no asyncio maintenance mocks).

**Residual gap:** Inbound **Subscribe** full §5–§8 negotiation matrix (product-driven). WS-Scan audit compliance module added (`tests/test_ws_scan_audit_compliance.py` — §6 retrieve timing/fault logs, §7 ack, §11 push_only, §13–§14 parsers/headers, §16 config guard, §17 Get URL).

**Done when:** Pytest coverage maps to audit checklist §11-style scenarios for both **client** and **server** roles airscand plays (eventing matrix covered for MVP hardening; WS-Scan audit-named module covers resolved audit themes; outbound **GetStatus** implemented for diagnostics).

**Verification:** CI runs compliance module; each `test_audit_ws_eventing_17_*` name maps to an audit § or fault bullet.

---

### 5. HTTP/SOAP header parity with reference traces (`docs/ws-scan_audit.md` Low §14)

**Gap:** Only `Content-Type: application/soap+xml; charset=utf-8` on some legs.

**Done when:** Captured Win10 ↔ device trace compared; optional `action` MIME parameter or **SOAPAction** added **only** if interop proof demands it.

**Verification:** Byte-level or header dict comparison test against golden file from real trace (redacted hostnames).

---

### 6. Developer and security posture (`docs/ROADMAP.md` Future)

**Gap:** No **CONTRIBUTING.md**, no **SECURITY.md**; threat model for trusted LAN only in design non-goals.

**Done when:** Both files exist at repo root with project-specific content (reporting channel, scope, build/test commands).

**Verification:** Maintainer review checklist; links from `README.md`.

---

### 8. Explicit scan lifecycle state machine (`docs/ROADMAP.md` Far-term; `docs/wia_client_audit.md` §8)

**Gap:** State spread across async tasks and flags.

**Done when:** Documented state diagram and enforced transitions (even if internal module only).

**Verification:** Invalid transition attempts raise or log **state violation**; happy path unchanged under tests.

---

### 10. Optional **`specs/`** entry point (documentation) — **done**

**Done:** [`specs/README.md`](specs/README.md) indexes `docs/protocol/`, audits, backlog, and audit-aligned pytest modules.

---

## Suggested execution order for MVP “hardening”

1. **Task 4** (compliance tests) after behavior stabilizes; remaining items per product need (bounded **RetrieveImage** retry, far-term items).

---

*Last updated: WS-Scan audit compliance module (`tests/test_ws_scan_audit_compliance.py`) + `specs/README.md` index.*
