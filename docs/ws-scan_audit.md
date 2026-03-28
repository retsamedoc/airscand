# WS-Scan compliance audit (Microsoft documentation)

This report compares the current `airscand` implementation (primarily [`app/ws_eventing_client.py`](../app/ws_eventing_client.py), [`app/ws_scan.py`](../app/ws_scan.py), and [`app/scan_receiver.py`](../app/scan_receiver.py)) to Microsoft’s **WSD Scan Service (WS-Scan)** element and operation documentation in [windows-driver-docs](https://github.com/MicrosoftDocs/windows-driver-docs/tree/main/windows-driver-docs-pr/image). Namespace URIs in the product often use `http://schemas.microsoft.com/windows/2006/08/wdp/scan` (with `wscn` / `sca` prefixes in traces); older doc examples sometimes show `2006/01` or `https`—implementation uses `2006/08` + `http`, which matches common Epson traces.

**Scope:** SOAP actions and bodies for outbound client behavior, inbound handler behavior, and image receive path. WS-Eventing and WS-Transfer are touched only where they interact with WS-Scan.

---

## Summary table (by severity)

| Severity | Count | Themes |
|----------|------:|--------|
| Critical | 0 | _(none — see [Critical (resolved)](#critical-resolved))_ |
| High     | 0 | _(none — see [High (resolved)](#high-resolved))_ |
| Medium   | 1 | Pull vs push image delivery (#11) _(**#7**, **#9**, **#12**: [Medium (resolved)](#medium-7-9-12-resolved); former #8/#10: [Medium (resolved)](#medium-8-10-resolved))_ |
| Low      | 5 | Parsing robustness, HTTP/SOAP headers, fault **Detail**, handler edge cases |

---

## Critical (resolved) {#critical-resolved}

### 1. `RetrieveImageRequest` uses **JobToken** from `CreateScanJobResponse` only — **Resolved**

**Reference:** [RetrieveImageRequest](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/retrieveimagerequest.md); [CreateScanJobResponse](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/createscanjobresponse.md).

**Implementation:** [`parse_create_scan_job_response`](../app/ws_eventing_client.py) extracts **JobToken**. [`run_scan_available_chain`](../app/ws_eventing_client.py) issues **RetrieveImage** only when **JobToken** is present. [`build_retrieve_image_request`](../app/ws_eventing_client.py) sends **JobId** and **JobToken** only (no **DestinationToken** fallback).

---

### 2. `DestinationToken` sourcing for device-initiated scans — **Resolved** (residual regex risk)

**Reference:** [CreateScanJobRequest](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/createscanjobrequest.md).

**Implementation:** **SubscribeResponse** may include multiple **`DestinationResponse`** elements; [`extract_subscribe_destination_tokens_by_client_context`](../app/ws_eventing_client.py) builds **`ClientContext` → `DestinationToken`** (persisted as **`scanner_subscribe_destination_tokens`**). **`CreateScanJob`** uses the token for **`ClientContext`** from **`ScanAvailableEvent`** when it matches; otherwise the first token in map order, then legacy single-string / env override (**`use_env_subscribe_destination_token_only`** when **`WSD_SUBSCRIBE_DESTINATION_TOKEN`** is set). Broader **DestinationToken** precedence after subscribe resolution: **ScanAvailableEvent** body, event **Identifier**, **`wsa:MessageID`** on **ValidateScanTicketResponse**, body **DestinationToken**, persisted **SubscribeResponse** **Identifier**. **ScanIdentifier** is separate.

**Residual risk:** Regex-based extraction (Low #13).

---

## High (resolved) {#high-resolved}

### 3. Device-driven **`ScanTicket`** — **Resolved**

**Reference:** [DefaultScanTicket](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/defaultscanticket.md).

**Implementation:** [`resolve_scan_ticket_xml_for_chain`](../app/ws_eventing_client.py) extracts inner **ScanTicket** from **DefaultScanTicket** when **GetScannerElements** metadata exists; otherwise **`SCAN_TICKET_TEMPLATE_XML`**. Validate/create builders accept **`scan_ticket_xml`**.

---

### 4. Inbound **`CreateScanJobResponse`** — **Resolved**

**Reference:** [CreateScanJobResponse](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/createscanjobresponse.md).

**Implementation:** [`build_create_scan_job_response`](../app/ws_scan.py) includes **JobId**, **JobToken**, **ImageInformation**, **DocumentFinalParameters**.

---

### 5. **`RetrieveImage` eligibility** — **Resolved**

**Implementation:** Gated on **JobId** + **JobToken** from **CreateScanJobResponse**, not on **destination_token**.

---

### 6. **CreateScanJob → RetrieveImage** timing and faults — **Resolved**

**Reference:** [CreateScanJobResponse remarks](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/createscanjobresponse.md).

**Implementation:** [`run_scan_available_chain`](../app/ws_eventing_client.py) logs **`retrieve_elapsed_sec`**, **`within_retrieve_window_60s`**, warns if **> 60** s, and warns on **JobTimedOut** / **ClientErrorNoImagesAvailable** / **NoImagesAvailable** in **`fault_subcode`**.

---

## Medium (resolved) {#medium-7-9-12-resolved}

### 7. `ScanAvailableEvent` acknowledgment — **Resolved**

**Reference:** WS-Addressing / SOAP sink behavior for event delivery (see also [ws-eventing_audit.md](ws-eventing_audit.md) §10).

**Implementation:** [`build_scan_available_event_ack_response`](../app/ws_scan.py) returns a SOAP 1.2 envelope with `Content-Type: application/soap+xml`, `wsa:RelatesTo` matching the notification `wsa:MessageID`, `wsa:Action` `.../ScanAvailableEventResponse` (synthetic URI—not a documented WS-Scan response element; used only as a typed HTTP ack), and empty `soap:Body`. [`handle_wsd`](../app/ws_scan.py) uses this for **ScanAvailableEvent** instead of `text/plain` `OK`.

---

### 9. `CreateScanJobRequest` retry on `ClientErrorInvalidDestinationToken` — **Resolved** (config-gated)

**Reference:** [CreateScanJobRequest](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/createscanjobrequest.md).

**Implementation:** [`run_scan_available_chain`](../app/ws_eventing_client.py) still supports a single retry with `DestinationToken` omitted when the first **CreateScanJob** returns `wscn:ClientErrorInvalidDestinationToken` and a token was sent. The retry is gated by **`Config.create_scan_job_retry_invalid_destination_token`** / env **`WSD_CREATE_SCAN_JOB_RETRY_INVALID_DESTINATION_TOKEN`** (default **true**). [`handle_wsd`](../app/ws_scan.py) passes the flag into the chain.

---

### 12. Child element order in `CreateScanJobRequest` — **Resolved**

**Reference:** [CreateScanJobRequest](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/createscanjobrequest.md) example (child sequence).

**Implementation:** [`build_create_scan_job_request`](../app/ws_eventing_client.py) emits **`ScanIdentifier`** (if present), then **`DestinationToken`** (if present), then **`ScanTicket`**, matching Microsoft’s published example order. The doc table lists **DestinationToken** before **ScanIdentifier**; the example XML uses **ScanIdentifier** first—implementation follows the example sequence.

---

## Medium (resolved) {#medium-8-10-resolved}

### 8. `ValidationInfo` / **ValidTicket** — **Resolved**

**Reference:** [common error codes](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/common-wsd-scan-service-operation-error-codes.md).

**Implementation:** [`_valid_ticket_from_validate_response`](../app/ws_eventing_client.py) resolves **ValidTicket** only inside **ValidationInfo** when that element is present (including self-closing **ValidationInfo** without **ValidTicket**, treated as invalid). Responses with no **ValidationInfo** keep legacy behavior: optional top-level **ValidTicket**, else **ValidTicket** absent allows the chain to proceed on HTTP success.

---

### 10. **ScannerConfiguration** merged into **ScanTicket** (narrow) — **Resolved**

**Implementation:** [`resolve_scan_ticket_xml_for_chain`](../app/ws_eventing_client.py) passes **ScannerConfiguration** into [`_apply_scanner_configuration_to_scan_ticket_xml`](../app/ws_eventing_client.py), which adjusts **InputSource** when the ticket requests **Platen** / **ADF** / **Feeder** not enabled in configuration. Broader capability or profile merging remains optional future work.

---

## Medium

### 11. Image delivery: **RetrieveImage** (pull) vs push upload to `/scan`

**Reference:** Pull path is documented for **RetrieveImage**; push “scan to computer” may use separate HTTP upload conventions.

**Code:** [`handle_scan`](../app/scan_receiver.py) accepts raw POST bodies with minimal content-type handling—no WS-Scan multipart / STAP handling.

**Risk:** If the device only pushes and never serves **RetrieveImage**, the chain’s retrieve step is redundant or must be skipped based on **ScannerCapabilities** / job type.

**Recommendation:** Detect or configure **pull vs push** per device and **ImageTransfer** semantics when that data is exposed.

---

## Low

### 13. Regex-based SOAP parsing

**Code:** Action, MessageID, faults, and element extraction use regular expressions, not an XML namespace-aware parser.

**Risk:** Brittle with unusual prefixes, comments, or whitespace; possible false positives for nested **Status** in `parse_retrieve_image_response`.

**Recommendation:** Migrate hot paths to `xml.etree.ElementTree` or `lxml` with explicit namespaces.

---

### 14. SOAP HTTP headers

**Code:** `_post_soap` sets `Content-Type: application/soap+xml; charset=utf-8` only.

**Risk:** Some devices expect `action` parameters in MIME type or `SOAPAction` legacy headers.

**Recommendation:** Match a captured Win10 ↔ device trace byte-for-byte for the POST.

---

### 15. Fault **Detail** and vendor extensions

**Code:** `parse_soap_fault` extracts Code / Subcode / Reason only—not **Detail** (e.g. supported format lists).

**Risk:** Harder diagnostics for `InvalidArgs` and format-not-supported cases.

---

### 16. `handle_wsd` assumes `config` is present and valid

**Code:** Uses `config.advertise_addr` without an `isinstance(config, Config)` guard (unlike `handle_scan`).

**Risk:** Crashes if `app["config"]` is missing in tests or mis-wired.

---

### 17. **WS-Transfer Get** URL selection

**Code:** Preflight **Get** targets `/WDP/SCAN` when derived from discovery—reasonable for bring-up docs, not a WS-Scan operation per se.

**Note:** Informational; not a WS-Scan violation.

---

## Positive observations (relative to Microsoft element docs)

- **GetScannerElements** **RequestedElements** / **Name** values use **QName**-style strings (e.g. `sca:ScannerDescription`), consistent with [Name for RequestedElements element](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/name-for-requestedelements-element.md).
- **Outbound** `CreateScanJobRequest` includes **ScanIdentifier**, **DestinationToken**, and **ScanTicket** when applicable—matches Microsoft’s example child sequence for device-initiated flow ([CreateScanJobRequest](https://github.com/MicrosoftDocs/windows-driver-docs/blob/main/windows-driver-docs-pr/image/createscanjobrequest.md)).
- **ValidateScanTicketRequest** / **CreateScanJobRequest** use inner **ScanTicket** from **DefaultScanTicket** when the metadata probe succeeds; **ScannerConfiguration** may adjust **InputSource**; otherwise the Win10-like template ([`resolve_scan_ticket_xml_for_chain`](../app/ws_eventing_client.py)).
- **ValidateScanTicketResponse** with **ValidationInfo** requires **ValidTicket** inside that block ([`_valid_ticket_from_validate_response`](../app/ws_eventing_client.py)).
- **WS-Addressing** on outbound requests includes **Action**, **To**, **MessageID**, **ReplyTo**, optional **From**—aligned with common WS-* SOAP usage in the same doc set.

---

## Suggested remediation order

1. ~~Parse and use **JobToken** from **CreateScanJobResponse** for **RetrieveImage**; correct **DestinationToken** sourcing~~ — done (see [Critical (resolved)](#critical-resolved)).
2. ~~Build **ScanTicket** from **GetScannerElements** **DefaultScanTicket** when available~~ — done (see [High (resolved)](#high-resolved) §3).
3. ~~Expand inbound **CreateScanJobResponse**~~ — done ([High (resolved)](#high-resolved) §4).
4. ~~Log create→retrieve elapsed time and timeout / no-image faults~~ — done ([High (resolved)](#high-resolved) §6).
5. ~~**ValidationInfo** / **ValidTicket**; **ScannerConfiguration** vs **ScanTicket**~~ — done ([Medium (resolved) §8 and §10](#medium-8-10-resolved)).
6. ~~Revisit **CreateScanJob** retry (Medium #9)~~ — gated by config (see [Medium (resolved) §9](#medium-7-9-12-resolved)).

---

*Generated from repository state and Microsoft `windows-driver-docs` WS-Scan pages (paths under `windows-driver-docs-pr/image/`). Update this file when protocol behavior or doc references change.*
