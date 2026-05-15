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

---

## Backlog (incomplete) — by priority

### 2. Documentation reconciliation (audits, ROADMAP, status)

**Gap:** No remaining drift tracked for outbound **Renew** / shutdown **Unsubscribe** vs the docs listed in **Done when** (as of this refresh).

**Done when:** `docs/status.md` describes **observed** outbound eventing (Renew, manager EPR fields, shutdown Unsubscribe) and Phase 5 lists remaining hardening; `docs/ws-eventing_audit.md` and `docs/ROADMAP.md` distinguish **inbound** sink/manager gaps vs **outbound** residual hardening; any cross-links from architecture/design docs stay consistent.

**Verification:** Doc-only review checklist; no code behavior change required for this task’s completion.

---

### 3. `SoapHttpClient` connect vs read timeouts (`app/soap/transport.py`, `app/config.py`)

**Gap:** Single **`ClientTimeout(total=...)`** per call; WIA audit §3 expects configurable **connect** and **read** splits (`docs/wia_client_audit.md`).

**Done when:** Environment variables (names TBD in implementation) set **connect** and **read** timeouts independently; defaults preserve current effective behavior or are justified in `docs/configuration.md`.

**Verification:**

- Unit test with mocked aiohttp session or timer injection: client uses distinct connect vs read values.
- Integration-style test optional: server that accepts TCP then delays past read bound triggers read timeout, not connect.

---

### 4. `SubscriptionEnd` support (WS-Eventing)

**Gap:** No builder/parser/send path (`docs/ws-eventing_audit.md` §3; grep confirms no `SubscriptionEnd` in code).

**Done when:** Product policy documented (when airscand emits or must accept **SubscriptionEnd**); implementation matches policy for **EndTo** / teardown.

**Verification:**

- If outbound emission is in scope: when subscription is torn down unexpectedly (define triggers), a one-way notification matching expected **Action** and addressing is sent (mock transport records XML).
- If inbound only: parser + handler acknowledges or logs per interop needs without breaking sink.

---

### 5. Inbound **Subscribe** contract enforcement (delivery, sink EPR, expiration grants)

**Gap:** **NotifyTo** / **EndTo** / **Expires** request handling and granted expiration computation not validated on server (`docs/ws-eventing_audit.md` §5, §6, §8, §13).

**Done when:** Parsed subscribe body drives response; invalid combinations return correct faults; granted **Expires** is computed (not hard-coded) where spec requires.

**Verification:** Matrix of XML fixtures → **fault vs SubscribeResponse** with expected **Expires** bounds; includes “filter present but unsupported” path.

---

### 6. Multi-**XAddr** failover (`app/discovery.py`, orchestration)

**Gap:** Discovery returns first **XAddr** only; no ordered retry on SOAP failures (`docs/wia_client_audit.md` §4).

**Done when:** On outbound SOAP failure to first **XAddr**, try remaining addresses in **ProbeMatches** order (policy for which errors retry configurable or documented).

**Verification:**

- Test double: discovery returns two **XAddrs**; first host fails connect, second succeeds → registration or scan chain succeeds using second.
- Logs include which **XAddr** was selected per attempt.

---

### 7. Outbound SOAP response validation (**RelatesTo**, **Action**) (`app/ws_eventing_client.py`, `app/soap/transport.py`)

**Gap:** Responses not asserted against outbound **MessageID** / expected action (`docs/wia_client_audit.md` §5).

**Done when:** Critical operations (at minimum **CreateScanJob**, **RetrieveImage**, **ValidateScanTicket**, **Subscribe**) optionally enforce **RelatesTo** == sent **MessageID** and **Action** matches expected response action; failures surface as structured errors/logs and predictable chain abort.

**Verification:** Fixture responses with wrong **RelatesTo** → handler raises or returns error dict that stops chain; correct fixture still passes.

---

### 8. **RetrieveImage** integrity / truncation handling (`docs/wia_client_audit.md` §7+)

**Gap:** Limited explicit validation of full document bytes / truncation vs **Content-Length** / MTOM completeness.

**Done when:** Documented behavior for partial MTOM, missing parts, and size mismatch; implementation matches (retry, fail, or warn-only per product choice).

**Verification:** Tests with synthetic MTOM: complete image passes; truncated / missing CID fails with explicit outcome; logs include byte counts and outcome.

---

### 9. Namespace-aware XML on critical eventing and fault paths (`docs/ws-eventing_audit.md` §11)

**Gap:** Regex-based extraction for identifiers, manager EPR, etc.

**Done when:** Identified hot paths use **ElementTree** (or agreed library) with explicit namespace URIs; regression tests include prefix permutations for the same logical document.

**Verification:** Same semantic XML with different prefixes yields identical parsed fields; maliciously nested duplicate tags do not pick wrong inner match.

---

### 10. Pull vs push image delivery strategy (`docs/ws-scan_audit.md` Medium §11)

**Gap:** **RetrieveImage** path always attempted for device-initiated flow; push-only devices may need different handling.

**Done when:** Configuration or capability-driven path selection documented and implemented.

**Verification:** With “push-only” fixture profile, chain skips pull retrieve and still persists scan when upload occurs (or documents that push-only is unsupported).

---

### 11. Contract / compliance test suite expansion (`docs/ws-eventing_audit.md` §17)

**Gap:** Limited tests for **fault mapping**, **subscription lifecycle** edge cases, **Renew** failure leading to resubscribe, **inbound** manager behavior.

**Done when:** Pytest coverage maps to audit checklist §11-style scenarios for both **client** and **server** roles airscand plays.

**Verification:** CI runs new tests; each test name maps to a bullet in audit or WIA spec section.

---

### 12. HTTP/SOAP header parity with reference traces (`docs/ws-scan_audit.md` Low §14)

**Gap:** Only `Content-Type: application/soap+xml; charset=utf-8` on some legs.

**Done when:** Captured Win10 ↔ device trace compared; optional `action` MIME parameter or **SOAPAction** added **only** if interop proof demands it.

**Verification:** Byte-level or header dict comparison test against golden file from real trace (redacted hostnames).

---

### 13. Fault **Detail** extraction (`docs/ws-scan_audit.md` Low §15)

**Gap:** `parse_soap_fault` does not surface **Detail** for diagnostics.

**Done when:** **Detail** (or subset) available in parsed dict / logs for **InvalidArgs** and similar.

**Verification:** Fixture fault with **Detail** → structured log field or parser key populated.

---

### 14. `handle_wsd` defensive **config** wiring (`docs/ws-scan_audit.md` Low §16)

**Gap:** Assumes `app["config"]` present (`isinstance` guard unlike `handle_scan`).

**Done when:** Missing/malformed config returns controlled error response without uncaught exception.

**Verification:** aiohttp test client POST without config → 500 or fault with no stack trace leak in production mode (optional: assert log warning).

---

### 15. Developer and security posture (`docs/ROADMAP.md` Future)

**Gap:** No **CONTRIBUTING.md**, no **SECURITY.md**; threat model for trusted LAN only in design non-goals.

**Done when:** Both files exist at repo root with project-specific content (reporting channel, scope, build/test commands).

**Verification:** Maintainer review checklist; links from `README.md`.

---

### 16. Explicit scan lifecycle state machine (`docs/ROADMAP.md` Far-term; `docs/wia_client_audit.md` §8)

**Gap:** State spread across async tasks and flags.

**Done when:** Documented state diagram and enforced transitions (even if internal module only).

**Verification:** Invalid transition attempts raise or log **state violation**; happy path unchanged under tests.

---

### 17. **CancelJob** and abandoned-job cleanup (`docs/ROADMAP.md` Far-term)

**Gap:** Not implemented per audits.

**Done when:** Spec’d behavior for cancel from host side and device side; implementation + tests.

**Verification:** Cancel during poll / retrieve yields defined terminal state and no resource leak (mock scanner).

---

### 18. Optional **`specs/`** entry point (documentation)

**Gap:** Empty **`specs/`** while **`docs/protocol/`** holds specs.

**Done when:** `specs/README.md` (or index) lists canonical doc paths and audit files for AI/human navigation.

**Verification:** Link check in CI or manual; `IMPLEMENTATION_PLAN.md` references it.

---

## Suggested execution order for MVP “hardening”

1. **Task 2** (doc truth) so all contributors align on what already ships.  
2. **Task 5** (deeper inbound **Subscribe** contract) — highest interoperability risk for non-Epson peers alongside remaining audit gaps.  
3. **Task 3** (timeouts) — low risk, high operability.  
4. **Tasks 11 + 9** (tests + parsing robustness) in parallel after behavior stabilizes.  
5. Remaining items per product need (failover, SubscriptionEnd, pull/push, far-term items).

---

*Last updated: `/wsd` unknown or missing `wsa:Action` returns SOAP faults; audit §4/§9 aligned.*
