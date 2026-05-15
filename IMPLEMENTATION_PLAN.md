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
- **SubscribeResponse** parsing: identifier, expires, subscription manager address + reference parameters XML, destination token map (`app/soap/parsers/eventing.py`).
- **Device-initiated scan chain**: **ScanAvailableEvent** SOAP ack, **ValidateScanTicket** → **CreateScanJob** → optional **GetJobStatus** → **RetrieveImage** / MTOM, coordination with **ScannerStatusSummaryEvent** (`app/ws_scan.py`, `app/ws_eventing_client.py`, audits).
- **Push path** `/scan`: atomic save, empty body rejection (`app/scan_receiver.py`, `app/scan_storage.py`, tests).
- **Inbound WS-Eventing subscription manager** (`app/ws_scan.py`, `app/inbound_eventing_registry.py`, `app/soap/parsers/inbound_eventing.py`, `app/soap/builders/faults.py`, `app/soap/envelope.py`): **Subscribe** allocates stable **Identifier** + granted **Expires**; **Renew** extends lease; **GetStatus** returns stored expiration without mutating lease; **Unsubscribe** removes state; unknown/expired ids and validation failures return **SOAP 1.2 faults** (`tests/test_ws_scan.py`).
- **Unknown or missing `wsa:Action` on `/wsd`:** SOAP 1.2 fault responses (`wsa:ActionNotSupported` / `wse:InvalidMessage`) with `application/soap+xml`, structured logs (`soap_action`, `wsa_message_id`); no `text/plain` success for those POSTs (`tests/test_ws_scan.py`).

- **Documentation reconciliation (status, ROADMAP, architecture, audits):** `docs/status.md` Phase 5 distinguishes **inbound shipped vs residual** and **outbound residual** (why: avoids duplicating work on already-landed SOAP paths); `docs/ROADMAP.md` near-term matches; `docs/architecture.md` package map matches `app/soap/` layout; `docs/ws-eventing_audit.md` defines outbound vs inbound terminology at top.
- **Outbound SOAP HTTP timeouts:** `SoapHttpClient` uses aiohttp `ClientTimeout(sock_connect=…, sock_read=…)`; `WSD_SOAP_HTTP_CONNECT_TIMEOUT_SEC` (default **10**) and optional `WSD_SOAP_HTTP_READ_TIMEOUT_SEC` (global read override); `main.configure_soap_http_client_from_config` after `Config()` (`tests/test_soap_transport.py`, `tests/test_config.py`).
- **Inbound Subscribe validation (MVP):** optional **`wse:EndTo`** requires non-empty **`wsa:Address`** when **`EndTo`** is present; **`EndTo`** may differ from **`NotifyTo`** because manager-emitted **`SubscriptionEnd`** is POSTed to **`EndTo`** (or **`NotifyTo`** when **`EndTo`** is omitted). Non-empty invalid **`wse:Expires`** → **`InvalidExpirationTime`**; filter/delivery faults unchanged (`app/soap/parsers/inbound_eventing.py`, `tests/test_inbound_eventing.py`, `tests/test_ws_scan.py`).
- **`SubscriptionEnd` (WS-Eventing, inbound roles):** When a managed lease expires without **Renew**, or **Unsubscribe**/**Renew**/**GetStatus** hits an already-expired id, the manager queues **`SubscriptionEnd`** (SOAP **`SubscriptionEnd`** action, **Status** URI `SourceCancelling`) to the stored subscriber EPR; **`main._inbound_subscription_lease_sweep_loop`** also expires idle leases every 5s. The sink accepts inbound **`SubscriptionEnd`** notifications and returns **`SubscriptionEndResponse`** (`app/inbound_eventing_registry.py`, `app/inbound_subscription_end_delivery.py`, `app/soap/builders/eventing.py`, `app/soap/namespaces.py`, `app/soap/parsers/subscription_end.py`, `app/ws_scan.py`, `main.py`, `tests/test_subscription_end.py`, `tests/test_ws_scan.py`). *Why tests matter:* without them, lease teardown silently breaks peers that rely on **EndTo** correlation or expect SOAP (not bare HTTP) for teardown.
- **Multi-XAddr registration failover:** [`discover_scanner_xaddrs`](app/discovery.py) returns the full **ProbeMatches** list in order; [`main._eventing_registration_loop`](main.py) tries each candidate and advances on transport-layer failures classified by [`is_scanner_xaddr_transport_failover`](app/soap/transport.py) (`asyncio.TimeoutError`, `ClientConnectorError`, `ClientOSError`). Logs include `xaddr_attempt_index`, `xaddr_candidates_total`, and `scanner_xaddr` per attempt (`tests/test_discovery.py`, `tests/test_main_registration.py`, `tests/test_soap_transport.py`). *Residual:* per-scan outbound legs after registration still target `config.scanner_xaddr` only (no mid-chain rotation).

---

## Backlog (incomplete) — by priority

### 3. Outbound SOAP response validation (**RelatesTo**, **Action**) (`app/ws_eventing_client.py`, `app/soap/transport.py`)

**Gap:** Responses not asserted against outbound **MessageID** / expected action (`docs/wia_client_audit.md` §5).

**Done when:** Critical operations (at minimum **CreateScanJob**, **RetrieveImage**, **ValidateScanTicket**, **Subscribe**) optionally enforce **RelatesTo** == sent **MessageID** and **Action** matches expected response action; failures surface as structured errors/logs and predictable chain abort.

**Verification:** Fixture responses with wrong **RelatesTo** → handler raises or returns error dict that stops chain; correct fixture still passes.

---

### 4. **RetrieveImage** integrity / truncation handling (`docs/wia_client_audit.md` §7+)

**Gap:** Limited explicit validation of full document bytes / truncation vs **Content-Length** / MTOM completeness.

**Done when:** Documented behavior for partial MTOM, missing parts, and size mismatch; implementation matches (retry, fail, or warn-only per product choice).

**Verification:** Tests with synthetic MTOM: complete image passes; truncated / missing CID fails with explicit outcome; logs include byte counts and outcome.

---

### 5. Namespace-aware XML on critical eventing and fault paths (`docs/ws-eventing_audit.md` §11)

**Gap:** Regex-based extraction for identifiers, manager EPR, etc.

**Done when:** Identified hot paths use **ElementTree** (or agreed library) with explicit namespace URIs; regression tests include prefix permutations for the same logical document.

**Verification:** Same semantic XML with different prefixes yields identical parsed fields; maliciously nested duplicate tags do not pick wrong inner match.

---

### 6. Pull vs push image delivery strategy (`docs/ws-scan_audit.md` Medium §11)

**Gap:** **RetrieveImage** path always attempted for device-initiated flow; push-only devices may need different handling.

**Done when:** Configuration or capability-driven path selection documented and implemented.

**Verification:** With “push-only” fixture profile, chain skips pull retrieve and still persists scan when upload occurs (or documents that push-only is unsupported).

---

### 7. Contract / compliance test suite expansion (`docs/ws-eventing_audit.md` §17)

**Gap:** Limited tests for **fault mapping**, **subscription lifecycle** edge cases, **Renew** failure leading to resubscribe, **inbound** manager behavior.

**Done when:** Pytest coverage maps to audit checklist §11-style scenarios for both **client** and **server** roles airscand plays.

**Verification:** CI runs new tests; each test name maps to a bullet in audit or WIA spec section.

---

### 8. HTTP/SOAP header parity with reference traces (`docs/ws-scan_audit.md` Low §14)

**Gap:** Only `Content-Type: application/soap+xml; charset=utf-8` on some legs.

**Done when:** Captured Win10 ↔ device trace compared; optional `action` MIME parameter or **SOAPAction** added **only** if interop proof demands it.

**Verification:** Byte-level or header dict comparison test against golden file from real trace (redacted hostnames).

---

### 9. Fault **Detail** extraction (`docs/ws-scan_audit.md` Low §15)

**Gap:** `parse_soap_fault` does not surface **Detail** for diagnostics.

**Done when:** **Detail** (or subset) available in parsed dict / logs for **InvalidArgs** and similar.

**Verification:** Fixture fault with **Detail** → structured log field or parser key populated.

---

### 10. `handle_wsd` defensive **config** wiring (`docs/ws-scan_audit.md` Low §16)

**Gap:** Assumes `app["config"]` present (`isinstance` guard unlike `handle_scan`).

**Done when:** Missing/malformed config returns controlled error response without uncaught exception.

**Verification:** aiohttp test client POST without config → 500 or fault with no stack trace leak in production mode (optional: assert log warning).

---

### 11. Developer and security posture (`docs/ROADMAP.md` Future)

**Gap:** No **CONTRIBUTING.md**, no **SECURITY.md**; threat model for trusted LAN only in design non-goals.

**Done when:** Both files exist at repo root with project-specific content (reporting channel, scope, build/test commands).

**Verification:** Maintainer review checklist; links from `README.md`.

---

### 12. Explicit scan lifecycle state machine (`docs/ROADMAP.md` Far-term; `docs/wia_client_audit.md` §8)

**Gap:** State spread across async tasks and flags.

**Done when:** Documented state diagram and enforced transitions (even if internal module only).

**Verification:** Invalid transition attempts raise or log **state violation**; happy path unchanged under tests.

---

### 13. **CancelJob** and abandoned-job cleanup (`docs/ROADMAP.md` Far-term)

**Gap:** Not implemented per audits.

**Done when:** Spec’d behavior for cancel from host side and device side; implementation + tests.

**Verification:** Cancel during poll / retrieve yields defined terminal state and no resource leak (mock scanner).

---

### 14. Optional **`specs/`** entry point (documentation)

**Gap:** Empty **`specs/`** while **`docs/protocol/`** holds specs.

**Done when:** `specs/README.md` (or index) lists canonical doc paths and audit files for AI/human navigation.

**Verification:** Link check in CI or manual; `IMPLEMENTATION_PLAN.md` references it.

---

## Suggested execution order for MVP “hardening”

1. **Tasks 7 + 5** (tests + parsing robustness) in parallel after behavior stabilizes.  
2. Remaining items per product need (RelatesTo validation, pull/push, far-term items).

---

*Last updated: multi-XAddr registration failover (`discover_scanner_xaddrs`, `main`, transport classifier); backlog 3–14.*
