# WIA over WSD (WS-Scan) client — compliance audit

This report maps the [WIA client specification](protocol/wia_client_spec.md) to the current **airscand** codebase. It is a **client-behavior** audit: outbound discovery, SOAP, WS-Scan operations, robustness, and optional eventing.

**Primary implementation:** [`app/soap/`](../app/soap/) (shared SOAP shell, transport, parsers), [`app/ws_eventing_client.py`](../app/ws_eventing_client.py) (orchestration + re-exports), [`app/discovery.py`](../app/discovery.py) (WS-Discovery client), [`main.py`](../main.py) (registration loop), [`app/ws_scan.py`](../app/ws_scan.py) (inbound SOAP for event delivery and test harness responses). Related: [`app/config.py`](../app/config.py), [`docs/ws-scan_audit.md`](ws-scan_audit.md), [`docs/ws-eventing_audit.md`](ws-eventing_audit.md).

---

## Executive summary

The project implements a **device-initiated** path (WS-Eventing **ScanAvailableEvent** → **ValidateScanTicket** → **GetScannerElements** (metadata) → **CreateScanJob** → optional **GetJobStatus** polling → **RetrieveImage**) that matches real Epson-style interop documented elsewhere in this repo. Several **normative items** in the WIA client spec are **not implemented** or only partially met—most notably **CancelJob**, **response RelatesTo validation**, **separate connect/read timeouts**, **multi-XAddr failover**, and **RetrieveImage document handling / integrity checks**. **GetJobStatus** polling exists but may be **disabled by vendor profile** (e.g. Epson WF-3640 default). Optional eventing is implemented; **fallback to job-status polling** when eventing fails is not.

---

## Section-by-section findings

### §2 Normative dependencies

| Requirement | Status | Notes |
|-------------|--------|--------|
| SOAP 1.2 | **Met** | `NS_SOAP` uses `http://www.w3.org/2003/05/soap-envelope` (SOAP 1.2) in outbound envelopes. |
| WS-Addressing 2004/08 | **Met** | `Action`, `To`, `MessageID`, `ReplyTo` on outbound requests. |
| WS-Discovery | **Met** | Multicast probe and `ProbeMatches` handling in [`discover_scanner_xaddr`](../app/discovery.py). |
| WS-Scan | **Partial** | Core operations present; **GetJobStatus** implemented when enabled (see §6–7). |
| WS-Eventing | **Partial** | Outbound **Subscribe** and inbound notify handling; full subscription lifecycle gaps are documented in [ws-eventing_audit.md](ws-eventing_audit.md). |

---

### §3 Transport and HTTP

| Requirement | Status | Notes |
|-------------|--------|--------|
| HTTP/1.1, POST for SOAP | **Met** | [`aiohttp`](https://docs.aiohttp.org/) client POSTs with `application/soap+xml`. |
| Chunked responses, keep-alive, premature close | **Partial** | Libraries handle chunked bodies; outbound SOAP uses a **process-wide shared** [`ClientSession`](../app/soap/transport.py) via [`SoapHttpClient`](../app/soap/transport.py) / [`default_soap_http_client`](../app/soap/transport.py) (connection reuse across legs is **used**; per-request sessions removed). |
| Configurable timeouts | **Partial** | `timeout_sec` parameters exist; **no env-driven split** into connect vs read. |
| Default connect ≤ 2s, read 2–10s | **Gap** | Defaults such as `timeout_sec=5.0` are a **single** deadline for the whole request, not connect/read split per §3.2. |
| Retry idempotent operations | **Partial** | Discovery repeats probes; **GetScannerElements** may retry with a reduced element set; no general idempotent-SOAP retry policy. |

---

### §4 Discovery

| Requirement | Status | Notes |
|-------------|--------|--------|
| Multicast Probe, listen for ProbeMatch | **Met** | [`build_probe`](../app/discovery.py) + [`discover_scanner_xaddr`](../app/discovery.py). |
| Filter for scanner type | **Clarify** | Probe uses `<wsd:Types>wscn:ScanDeviceType</wsd:Types>`. The spec text says `ScannerServiceType`; Microsoft WS-Scan materials typically use **ScanDeviceType**. Confirm target devices expect the same QName; align spec wording if needed. |
| Extract all XAddrs | **Met** | [`extract_xaddrs`](../app/discovery.py) splits space-separated list. |
| Attempt connection **in order** | **Gap** | [`discover_scanner_xaddr`](../app/discovery.py) returns **`xaddrs[0]`** only; later SOAP does not iterate remaining XAddrs on failure. |

---

### §5 SOAP construction and response validation

| Requirement | Status | Notes |
|-------------|--------|--------|
| Envelope with Header (Action, MessageID, To) + Body | **Met** | Outbound builders use [`app/soap/envelope.py`](../app/soap/envelope.py) and [`app/soap/parsers/`](../app/soap/parsers/); orchestration in [`ws_eventing_client.py`](../app/ws_eventing_client.py). |
| Unique MessageID per request | **Met** | [`new_message_id`](../app/soap/addressing.py) (`urn:uuid:…`). |
| ReplyTo anonymous | **Met** | `WSA_ANONYMOUS` on outbound scan/eventing requests. |
| Validate RelatesTo | **Gap** | Inbound discovery matches `relates_to == probe_mid`. Outbound **SOAP responses** from the scanner are **not** checked for `RelatesTo` equal to the outbound request `MessageID`; responses are parsed with regex for body/fault only. |
| Validate Action | **Partial** | Response `Action` is logged via [`extract_wsa_action`](../app/soap/addressing.py) in transport; not enforced against expected operation. |

---

### §6 Operation flow (critical)

The spec’s logical sequence is:

`Discovery → GetScannerElements → CreateScanJob → (poll GetJobStatus) → RetrieveImage`.

| Step | Status | Notes |
|------|--------|--------|
| GetScannerElements before job | **Met** | [`get_scanner_elements_metadata`](../app/ws_eventing_client.py) runs at start of [`run_scan_available_chain`](../app/ws_eventing_client.py); on failure the chain **continues** with a template ticket (tolerant, per §10). |
| CreateScanJob | **Met** | With **ValidateScanTicket** first (extra vs §16 minimal list; appropriate for push/eventing flows). |
| **GetJobStatus** loop until terminal | **Partial** | [`poll_get_job_status_until_ready`](../app/ws_eventing_client.py) (builders/parsers in [`app/soap/parsers/scan.py`](../app/soap/parsers/scan.py)) when enabled; **disabled** for some profiles (e.g. Epson WF-3640). |
| RetrieveImage when ready | **Partial** | When polling is enabled, **RetrieveImage** follows **GetJobStatus** readiness; otherwise optimistic single call. Strict §6.1 sequencing may still differ on edge cases. |

---

### §7 WS-Scan operations

| Operation / rule | Status | Notes |
|------------------|--------|--------|
| **GetScannerElements** — cache capabilities | **Partial** | Parsed into `scanner_metadata` for the chain; **no persistent cache** across events/sessions. |
| **GetScannerElements** — retry on failure | **Partial** | Reduced-QName retry on InvalidArgs-style faults. |
| **CreateScanJob** — input source, resolution, format | **Met** | [`SCAN_TICKET_TEMPLATE_XML`](../app/ws_eventing_client.py) and [`_apply_scanner_configuration_to_scan_ticket_xml`](../app/ws_eventing_client.py) adjust **InputSource**; resolution/format present in template **DocumentParameters**. |
| **CreateScanJob** — store JobId | **Met** | Parsed and returned in chain result. |
| **GetJobStatus** — poll until terminal, 200–500ms initial, backoff ~2s | **Partial** | Implemented in [`app/soap/parsers/scan.py`](../app/soap/parsers/scan.py) + [`poll_get_job_status_until_ready`](../app/ws_eventing_client.py); intervals align with intent; may be off by profile. |
| **RetrieveImage** — only when ready | **Partial** | Gated when polling enabled; see §6. |
| **RetrieveImage** — base64, large payloads, chunked | **Gap** | [`parse_retrieve_image_response`](../app/soap/parsers/scan.py) extracts **Status** and faults only; **no** decoding of document bytes, size limits, or integrity validation per §7.4. |
| **RetrieveImage** — truncated retry | **Gap** | No retry path for truncated image payload. |
| **CancelJob** | **Gap** | **Not implemented.** |

---

### §8 Client state machine

| Requirement | Status | Notes |
|-------------|--------|--------|
| Explicit states (Idle → … → Completed) | **Gap** | No named state machine type; behavior is **procedural** in `main` + `run_scan_available_chain`. |
| Track JobId lifecycle | **Partial** | Job id returned in dict; **no** global lifecycle across cancellations or abandoned jobs. |
| Prevent invalid transitions | **Not applicable / weak** | Without explicit states, transitions are implicit. |
| Clean up abandoned jobs | **Gap** | **CancelJob** not sent on user abort/timeout (§7.5). |

---

### §9 Error handling

| Requirement | Status | Notes |
|-------------|--------|--------|
| SOAP faults — parse/classify/retry | **Partial** | [`parse_soap_fault`](../app/soap/fault.py); targeted retry for **CreateScanJob** invalid destination token; **no** broad fault-driven retry matrix. |
| Network — retry transient, abort persistent | **Partial** | Registration loop backs off; per-request failures often surface once unless wrapped by caller. |
| Tolerance for malformed/missing headers/namespaces | **Partial** | Regex-based parsing aligns with “loose” §9.3 / §10 but is fragile compared to namespace-aware parsing (see [ws-eventing_audit.md](ws-eventing_audit.md)). |

---

### §10 WIA compatibility — retry GetJobStatus / RetrieveImage

| Requirement | Status | Notes |
|-------------|--------|--------|
| Retry **GetJobStatus** | **Partial** | Polling loop present when enabled; not a separate retry matrix for transient faults. |
| Retry **RetrieveImage** | **Gap** | No bounded retry loop for transient image faults or truncation (§10.2). |
| Limit retries | **Partial** | Some gates (e.g. create retry once); no unified limiter for image retrieval. |

---

### §11 Performance

| Requirement | Status | Notes |
|-------------|--------|--------|
| Avoid excessive polling (&lt; ~5 req/s), backoff | **Partial** | **GetJobStatus** uses initial interval + capped backoff when enabled. Eventing registration loop uses separate backoff. |
| Cache capabilities | **Partial** | In-memory for one chain only. |

---

### §12 Eventing (optional)

| Requirement | Status | Notes |
|-------------|--------|--------|
| Subscribe + handle Notify | **Met** | [`register_with_scanner`](../app/ws_eventing_client.py), inbound [`handle_wsd`](../app/ws_scan.py) for **ScanAvailableEvent**. |
| Fall back to polling if eventing fails | **Gap** | [`_eventing_registration_loop`](../main.py) retries discovery/subscribe with backoff; it does **not** use **GetJobStatus** as a substitute when subscriptions fail (§12 scan-progress fallback). |

---

## Compliance checklist (from spec §13) — mapped to this repo

| Item | Verdict | Evidence / gap |
|------|---------|----------------|
| Sends WS-Discovery Probe | **Yes** | [`build_probe`](../app/discovery.py) |
| Parses ProbeMatch correctly | **Yes** | [`_recv_discovery_match`](../app/discovery.py), `ACTION_PROBE_MATCHES` + `relates_to` |
| Extracts XAddrs | **Yes** | [`extract_xaddrs`](../app/discovery.py) |
| Generates valid SOAP envelopes | **Yes** | [`app/soap/envelope.py`](../app/soap/envelope.py), parsers under [`app/soap/parsers/`](../app/soap/parsers/) |
| Uses unique MessageIDs | **Yes** | [`new_message_id`](../app/soap/addressing.py) |
| Validates RelatesTo | **No** | Outbound SOAP responses |
| Calls GetScannerElements first | **Yes** | [`run_scan_available_chain`](../app/ws_eventing_client.py) |
| Creates scan job correctly | **Yes** | With ValidateScanTicket + ticket resolution |
| Polls status correctly | **Partial** | **GetJobStatus** when profile enables polling |
| Retrieves image only when ready | **Partial** | Status gate when polling enabled; else optimistic |
| Handles malformed responses | **Partial** | Regex + tolerant paths; not full XML |
| Retries transient failures | **Partial** | Selective retries |
| Handles timeouts | **Partial** | Single timeout value; not §3.2 defaults split |
| Tracks JobId lifecycle | **Partial** | Per-chain only |
| Prevents invalid transitions | **Weak** | No explicit machine |
| Cleans up jobs | **No** | No **CancelJob** |
| Works with real WSD scanner | **Yes** (reported) | [ws-scan_audit.md](ws-scan_audit.md) |
| Handles non-compliant devices | **Partial** | Heuristics and fallbacks; gaps above remain |

---

## Checklist — corrections and follow-ups

Use this as a prioritized backlog against [wia_client_spec.md](protocol/wia_client_spec.md).

### Critical (§6 / §7 sequencing)

- [x] **Implement `GetJobStatus`** (SOAP action + parser) and a **polling loop** after `CreateScanJob` (see [`app/soap/parsers/scan.py`](../app/soap/parsers/scan.py), [`poll_get_job_status_until_ready`](../app/ws_eventing_client.py)); vendor profiles may disable polling.
- [x] **Gate `RetrieveImage`** on job readiness from `GetJobStatus` when polling is enabled (fast/optimistic path when disabled).
- [ ] **Document or implement** the spec’s **ValidateScanTicket** position vs §16 minimal list (already required for eventing flows).

### High

- [ ] **Outbound SOAP response validation**: optionally verify `wsa:RelatesTo` matches the request `wsa:MessageID` and expected `wsa:Action` (with tolerance flags per §5.3).
- [ ] **Timeouts**: expose **connect** and **read** timeouts via config/env; align defaults with §3.2 (connect ≤ 2s, read 2–10s).
- [ ] **Multi-XAddr failover**: when discovering, try **each** XAddr in order for subsequent HTTP operations until one responds acceptably.
- [ ] **`RetrieveImage` body handling**: parse **Document** / base64 (or MTOM if needed), support large responses, **validate integrity** (e.g. magic bytes / length), **retry on truncation** per §7.4.

### Medium

- [ ] **CancelJob**: send on shutdown, user cancel, or timeout; tolerate devices that ignore it (§7.5).
- [x] **Connection reuse**: shared `ClientSession` via [`SoapHttpClient`](../app/soap/transport.py) (process-wide default client).
- [ ] **Idempotent SOAP retries**: define which operations are idempotent and retry policy (GET-like / safe replays).
- [ ] **Explicit client state machine** (§8): map `Idle` → `CapabilitiesLoaded` → `JobCreated` → `Polling` → `Retrieving` → terminal states; guard transitions.
- [ ] **Eventing fallback**: if subscribe never succeeds, document behavior; optionally add **GetJobStatus**-based polling for long-running jobs if a pull-only mode is added.

### Low / clarify

- [ ] **Probe `Types`**: confirm interoperability of `wscn:ScanDeviceType` vs spec name **ScannerServiceType** (§4.2); update spec or probe if devices require a different type token.
- [ ] **Cache GetScannerElements** across subscriptions/events when safe (§7.1 / §11).
- [ ] **Namespace-aware XML** for critical paths (reduce regex fragility while keeping tolerance).

---

## Related documents

- [ws-scan_audit.md](ws-scan_audit.md) — WS-Scan elements and Epson-focused behavior.
- [ws-eventing_audit.md](ws-eventing_audit.md) — WS-Eventing subscriber and sink gaps.
- [protocol/wia_client_spec.md](protocol/wia_client_spec.md) — normative source for this audit.

---

*Generated as a static audit; re-run when behavior or spec changes.*
