## ROADMAP

This roadmap tracks **remaining** work by timeline and references detailed context in:
- [`docs/wia_client_audit.md`](wia_client_audit.md)
- [`docs/ws-scan_audit.md`](ws-scan_audit.md)
- [`docs/ws-eventing_audit.md`](ws-eventing_audit.md)

### Near-term

- **WS-Eventing lifecycle correctness (critical)**: implement real subscription state for inbound `Subscribe` / `Renew` / `GetStatus` / `Unsubscribe` and return proper SOAP faults instead of placeholder success paths.  
  See `ws-eventing_audit` critical/high items (§1, §4, §5, §12).
- **Outbound eventing lease management (critical)**: persist manager EPR + expiry from `SubscribeResponse`; schedule `Renew`; implement clean subscription teardown behavior.  
  See `ws-eventing_audit` critical items (§2, §3, §7).
- **SOAP response correctness on sink endpoint**: replace plain-text fallback responses for unsupported SOAP actions with SOAP fault responses.  
  See `ws-eventing_audit` medium item (§9).
- **Subscribe contract enforcement**: validate delivery mode/filter/expiration and align `NotifyTo`/`EndTo` handling with profile expectations.  
  See `ws-eventing_audit` high/medium items (§5, §6, §8, §13).
- **Transport timeout split**: add env/config-driven connect/read timeout controls in `SoapHttpClient` (current single timeout remains).  
  See `wia_client_audit` §3 checklist.
- **Roadmap/documentation hygiene**: keep all changed implementation locations (`app/soap/*`, orchestration in `ws_eventing_client`) reflected in architecture/design/status and all audit references.

### Mid-term

- **WIA operation hardening**:
  - Multi-XAddr failover after discovery (try all candidate XAddrs in order).
  - Retrieve-image integrity and truncation handling / retry policy.
  - Explicit idempotent retry policy for SOAP operations.
  See `wia_client_audit` high/medium checklist.
- **WS-Scan follow-through**:
  - Confirm/adjust Probe `Types` interop choice where needed.
  - Cache `GetScannerElements` where safe across subscriptions/events.
  See `wia_client_audit` low/clarify items and `ws-scan_audit` remaining medium/low issues.
- **Eventing parsing robustness**: expand namespace-aware XML handling on critical eventing paths beyond regex parsing.
  See `ws-eventing_audit` medium item (§11).
- **Compliance-oriented tests**: add contract coverage for eventing lifecycle, fault mapping, renewal/status behavior, and subscription-end semantics.
  See `ws-eventing_audit` low item (§17).
- **WS-Scan handler hardening details**: add missing guardrails noted in audit deltas (e.g., handler assumptions) and document intentional deviations.
  See `ws-scan_audit` remaining low items.

### Far-term

- **Explicit client state machine** for scan lifecycle (`Idle -> CapabilitiesLoaded -> JobCreated -> Polling -> Retrieving -> terminal`) with transition guards and clearer failure handling.
  See `wia_client_audit` §8.
- **CancelJob and abandoned-job cleanup** (still out of scope for the mini-library refactor but tracked as product work).  
  See `wia_client_audit` §7.5 / §8.
- **Vendor profile growth**: extend `app/quirks` and `docs/protocol/vendor_quirks.md` as more hardware is validated.

### Future

- **Security and metadata posture**:
  - Document and/or implement stronger eventing subscription protections.
  - Clarify metadata/WSDL strategy if full standards alignment becomes a goal.
  See `ws-eventing_audit` low items.
- **Developer docs/policy**:
  - Add CONTRIBUTING guidance.
  - Add `SECURITY.md`.
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

### Historical completion details

- WS-Discovery Probe/Resolve response correctness and correlation.
- WS-Eventing registration loop with preflight `Get` and subscribe retries.
- WS-Scan device-initiated chain (`ValidateScanTicket -> CreateScanJob -> RetrieveImage`) and metadata probe flow.
- `/scan` persistence hardening (atomic writes, empty payload rejection, improved logging, tests).

