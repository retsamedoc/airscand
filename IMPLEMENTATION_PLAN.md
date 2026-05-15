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
- **Device-initiated scan chain**: **ScanAvailableEvent** SOAP ack, **ValidateScanTicket** → **CreateScanJob** → optional **GetJobStatus** → **RetrieveImage** / MTOM, coordination with **ScannerStatusSummaryEvent** (`app/ws_scan.py`, `app/ws_eventing_client.py`, audits).
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

---

## Backlog (incomplete) — by priority

### 4. Pull vs push image delivery strategy (`docs/ws-scan_audit.md` Medium §11)

**Gap:** **RetrieveImage** path always attempted for device-initiated flow; push-only devices may need different handling.

**Done when:** Configuration or capability-driven path selection documented and implemented.

**Verification:** With “push-only” fixture profile, chain skips pull retrieve and still persists scan when upload occurs (or documents that push-only is unsupported).

---

### 5. Contract / compliance test suite expansion (`docs/ws-eventing_audit.md` §17)

**Gap:** Limited tests for **fault mapping**, **subscription lifecycle** edge cases, **Renew** failure leading to resubscribe, **inbound** manager behavior.

**Done when:** Pytest coverage maps to audit checklist §11-style scenarios for both **client** and **server** roles airscand plays.

**Verification:** CI runs new tests; each test name maps to a bullet in audit or WIA spec section.

---

### 6. HTTP/SOAP header parity with reference traces (`docs/ws-scan_audit.md` Low §14)

**Gap:** Only `Content-Type: application/soap+xml; charset=utf-8` on some legs.

**Done when:** Captured Win10 ↔ device trace compared; optional `action` MIME parameter or **SOAPAction** added **only** if interop proof demands it.

**Verification:** Byte-level or header dict comparison test against golden file from real trace (redacted hostnames).

---

### 7. Fault **Detail** extraction (`docs/ws-scan_audit.md` Low §15)

**Gap:** `parse_soap_fault` does not surface **Detail** for diagnostics.

**Done when:** **Detail** (or subset) available in parsed dict / logs for **InvalidArgs** and similar.

**Verification:** Fixture fault with **Detail** → structured log field or parser key populated.

---

### 8. `handle_wsd` defensive **config** wiring (`docs/ws-scan_audit.md` Low §16)

**Gap:** Assumes `app["config"]` present (`isinstance` guard unlike `handle_scan`).

**Done when:** Missing/malformed config returns controlled error response without uncaught exception.

**Verification:** aiohttp test client POST without config → 500 or fault with no stack trace leak in production mode (optional: assert log warning).

---

### 9. Developer and security posture (`docs/ROADMAP.md` Future)

**Gap:** No **CONTRIBUTING.md**, no **SECURITY.md**; threat model for trusted LAN only in design non-goals.

**Done when:** Both files exist at repo root with project-specific content (reporting channel, scope, build/test commands).

**Verification:** Maintainer review checklist; links from `README.md`.

---

### 10. Explicit scan lifecycle state machine (`docs/ROADMAP.md` Far-term; `docs/wia_client_audit.md` §8)

**Gap:** State spread across async tasks and flags.

**Done when:** Documented state diagram and enforced transitions (even if internal module only).

**Verification:** Invalid transition attempts raise or log **state violation**; happy path unchanged under tests.

---

### 11. **CancelJob** and abandoned-job cleanup (`docs/ROADMAP.md` Far-term)

**Gap:** Not implemented per audits.

**Done when:** Spec’d behavior for cancel from host side and device side; implementation + tests.

**Verification:** Cancel during poll / retrieve yields defined terminal state and no resource leak (mock scanner).

---

### 12. Optional **`specs/`** entry point (documentation)

**Gap:** Empty **`specs/`** while **`docs/protocol/`** holds specs.

**Done when:** `specs/README.md` (or index) lists canonical doc paths and audit files for AI/human navigation.

**Verification:** Link check in CI or manual; `IMPLEMENTATION_PLAN.md` references it.

---

## Suggested execution order for MVP “hardening”

1. **Task 5** (compliance tests) after behavior stabilizes; remaining items per product need (bounded **RetrieveImage** retry, pull/push, far-term items).

---

*Last updated: namespace-aware ElementTree parsing for eventing / WS-A / faults (`tests/test_eventing_namespace_xml.py`); backlog renumbered 4–12.*
