# WS-Eventing compliance audit

This report compares the current **airscand** WS-Eventing-related code to the normative compliance contract in the **WS-Eventing Compliance Specification (AI-Oriented)** (subscription lifecycle, message formats, delivery semantics, faults, leasing, filtering, security SHOULDs, and checklist §11).

**Scope:** Outbound subscriber behavior in [`app/ws_eventing_client.py`](../app/ws_eventing_client.py) (orchestration), [`app/soap/builders/eventing.py`](../app/soap/builders/eventing.py) (Subscribe/Renew/Unsubscribe bodies), and [`app/soap/parsers/eventing.py`](../app/soap/parsers/eventing.py) (response parse helpers), [`app/soap/parsers/transfer.py`](../app/soap/parsers/transfer.py) (WS-Transfer **Get** preflight), plus [`main.py`](../main.py); inbound event-sink / minimal subscription-manager behavior in [`app/ws_scan.py`](../app/ws_scan.py); configuration in [`app/config.py`](../app/config.py). WS-Discovery and WS-Scan are out of scope except where they touch eventing.

**Roles in this codebase**

| Role | Where implemented | Notes |
|------|-------------------|--------|
| Subscriber | `register_with_scanner`, `_eventing_registration_loop`, `_eventing_maintenance_loop`, `renew_subscription`, `unsubscribe_from_scanner` | Sends `Subscribe`; persists manager URL + reference parameters + `Expires` from `SubscribeResponse` / `RenewResponse`; `_eventing_maintenance_loop` schedules `Renew` before lease fraction; `_unsubscribe_eventing_best_effort` on shutdown / failed renew. No outbound `GetStatus` client. |
| Event sink | `handle_wsd` (`ScanAvailableEvent`) | Receives notifications; for **ScanAvailableEvent** responds with SOAP 1.2 (`application/soap+xml`), `wsa:RelatesTo`, and [`build_scan_available_event_ack_response`](../app/ws_scan.py) (synthetic `ScanAvailableEventResponse` action). Unsupported actions still use plain `text/plain` “OK” in the default branch (§9). |
| Subscription Manager / Event Source (inbound) | `handle_wsd` for `Subscribe` / `Renew` / `GetStatus` / `Unsubscribe` | **MVP:** registry in `app/inbound_eventing_registry.py`, SOAP faults for bad ids / bad subscribe, **GetStatus** returns remaining lease without mutating expiry. Residual: **SubscriptionEnd**, fuller **EndTo**/grant matrix (§5–§8), header **Identifier** parsing robustness (§11). |

---

## Summary table (by severity)

| Severity | Count | Themes |
|----------|------:|--------|
| Critical | 1 | **`SubscriptionEnd`** missing (inbound subscription manager MVP: §1) |
| High | 3 | **SOAP faults** still missing for some paths (e.g. unknown WSD actions §9); **Subscribe** contract incomplete vs §5–§8 (**EndTo**, grants); **delivery mode** / **filter** edge cases |
| Medium | 4 | **Non-SOAP fallbacks** (#9); **regex** parsing (#11); **`GetStatus`** semantics (#12); **EndTo** / **Filter** (#13) _(notification ack for `ScanAvailableEvent`: [resolved §10](#10-scanavailableevent-notification-ack--resolved))_ |
| Low | 4 | Security SHOULDs; **WSDL/metadata**; test coverage gaps; **SOAP 1.1** vs **1.2** only |

---

## Critical

### 1. Inbound lifecycle operations — **implemented (MVP)** {#1-inbound-lifecycle-operations-implemented-mvp}

**Spec:** `Renew`, `GetStatus`, and `Unsubscribe` MUST be directed at the **Subscription Manager** EPR and MUST honor subscription identity; `GetStatus` MUST NOT mutate state; successful `Unsubscribe` MUST stop notifications for that subscription.

**Code (current):** [`handle_wsd`](../app/ws_scan.py) maintains subscriptions in [`app/inbound_eventing_registry.py`](../app/inbound_eventing_registry.py), validates inbound [`Subscribe`](../app/soap/parsers/inbound_eventing.py) (Push + optional Action filter), returns SOAP faults (WS-Addressing fault Action, HTTP 500) for unknown identifiers or unsupported subscribe contracts, and returns **GetStatus** `Expires` as the **remaining** lease duration without extending it.

**Residual:** No **SubscriptionEnd** yet (see §3). Inbound **Subscribe** does not yet enforce the full **EndTo** / **NotifyTo** / **Expires** matrix from §5–§8 (see backlog `IMPLEMENTATION_PLAN.md` item 6). Parsing remains ElementTree for Subscribe bodies and regex-oriented for management **Identifier** extraction in headers.

---

### 2. Outbound lease maintenance — **implemented** (residual notes)

**Spec:** Subscriptions are leased; `Renew` MUST extend expiration; management requests MUST target the **Subscription Manager** EPR returned in `SubscribeResponse`.

**Code (current):**

- **Parse + persist:** [`parse_subscribe_response`](../app/soap/parsers/eventing.py) extracts `identifier`, `Expires`, `subscription_manager_url`, and `subscription_manager_reference_parameters_xml` (regex on `wse:SubscriptionManager` inner XML). [`register_with_scanner`](../app/ws_eventing_client.py) returns these fields; [`_eventing_registration_loop`](../main.py) writes them to [`Config`](../app/config.py) (`scanner_eventing_subscribe_manager_url`, `scanner_eventing_subscribe_manager_reference_parameters_xml`, `scanner_eventing_subscription_id`, `scanner_eventing_subscribe_expires`, plus parallel `*_status` fields when a second subscription is used).
- **Renew:** [`_eventing_maintenance_loop`](../main.py) computes wake time from parsed `Expires` ([`parse_iso8601_duration_to_seconds`](../app/soap/parsers/eventing.py)) and `eventing_renew_after_fraction` / fallbacks in config, then calls [`renew_subscription`](../app/ws_eventing_client.py) against the stored manager URL and reference parameters. Successful [`parse_renew_response`](../app/soap/parsers/eventing.py) updates stored `Expires`. Failure exits the maintenance loop and the outer registration loop resubscribes after backoff.
- **Shutdown / cleanup:** [`_shutdown_services`](../main.py) invokes [`_unsubscribe_eventing_best_effort`](../main.py), which calls [`unsubscribe_from_scanner`](../app/ws_eventing_client.py) for `ScannerStatusSummary` then primary subscriptions when ids are present. Failed renew also triggers best-effort unsubscribe before resubscribe.

**Residual gaps (not the same as “missing Renew”):** Outbound **`GetStatus`** is still not implemented. EPR and body parsing remain **regex-based** (see §11). There is still no local handling of peer-driven subscription end beyond Renew/Unsubscribe HTTP/SOAP outcomes (see §3 for **`SubscriptionEnd`**).

---

### 3. `SubscriptionEnd` is not implemented (violates §3.7, §11.2)

**Spec:** `SubscriptionEnd` MUST be sent when a subscription ends unexpectedly; SHOULD include reason.

**Code:** No `SubscriptionEnd` action constant, builder, or send path appears in the codebase (grep: no matches).

**Risk:** Subscribers cannot distinguish unexpected termination from other failures; no standards-compliant teardown signal.

**Recommendation:** When subscription state expires or is revoked internally, emit `SubscriptionEnd` to the appropriate EPR (per policy for `EndTo` if used).

---

## High

### 4. Server does not generate WS-Eventing SOAP faults (violates §5, §11.5)

**Spec:** Faults such as `DeliveryModeRequestedUnavailable`, `InvalidExpirationTime`, `UnsupportedExpirationType`, `FilteringNotSupported` / `FilteringRequestedUnavailable`, `UnableToRenew`, `InvalidMessage`, etc., MUST be represented as SOAP faults with appropriate codes/reasons.

**Code:** [`handle_wsd`](../app/ws_scan.py) never builds `soap:Fault` responses for eventing. Unsupported actions fall through to `text/plain` “OK” (see §6 below).

**Risk:** Strict clients receive success or non-SOAP bodies where faults are required.

**Recommendation:** Centralize fault builders; map validation failures to the spec subcodes local names / namespaces used in your interop profile.

---

### 5. Inbound `Subscribe` does not validate message content (violates §3.2–3.3, §4.4, §7)

**Spec:** Event Source MUST validate **delivery mode**; unsupported mode MUST fault (optionally advertising supported modes). If filtering is requested but unsupported, MUST fault. `Subscribe` MUST include **Delivery** and **sink** EPR (NotifyTo); response MUST include **SubscriptionManager** EPR and **granted Expires**.

**Code:** [`handle_wsd`](../app/ws_scan.py) for `ACTION_SUBSCRIBE` ignores body; always returns `SubscribeResponse` with fixed `PT1H` and random identifier. No check of `Mode`, `NotifyTo`, `Filter`, or `Expires`.

**Risk:** Appears compliant in traces while accepting arbitrary or malicious subscribe payloads.

**Recommendation:** Parse body (namespace-aware XML); reject unsupported modes and filters with §5 faults; compute granted expiration.

---

### 6. `DeliveryModeRequestedUnavailable` path missing on both sides (violates §3.2, §4.4, §5)

**Spec:** Push MUST be supported; other modes MAY be extended; unsupported requested mode MUST fault.

**Code:** Client always emits Push in [`build_subscribe_request`](../app/ws_eventing_client.py). Server never inspects inbound `Delivery/@Mode`.

**Risk:** No way to negotiate or signal unsupported modes correctly when extending.

**Recommendation:** Server validates `Mode`; client remains Push-only until another mode is implemented.

---

### 7. Subscription Manager EPR retention — **implemented** (robustness still §11)

**Spec:** Returned manager EPR MUST uniquely identify the subscription and MUST be used for future lifecycle operations.

**Code:** [`parse_subscribe_response`](../app/soap/parsers/eventing.py) extracts manager `Address` and optional `ReferenceParameters` XML; [`renew_subscription`](../app/ws_eventing_client.py) / [`unsubscribe_from_scanner`](../app/ws_eventing_client.py) use the stored URL as SOAP `To` and pass reference-parameter XML into builders ([`effective_subscription_identifier_for_unsubscribe`](../app/soap/parsers/eventing.py) when the authoritative id lives in reference parameters).

**Residual:** Parsing is still regex-based; fragile markup can still break management interop (see §11).

---

### 8. Filtering is always requested on subscribe (violates §7 if peer does not support it)

**Spec:** If a filter is present and the event source does not support filtering, it MUST fault (`FilteringNotSupported` / `FilteringRequestedUnavailable` as appropriate).

**Code:** [`build_subscribe_request`](../app/ws_eventing_client.py) always includes `wse:Filter` with dialect `http://schemas.xmlsoap.org/ws/2006/02/devprof/Action` and action `ScanAvailableEvent`. Inbound server does not honor this rule when acting as event source.

**Risk:** Devices that strictly reject filters may fault; the stack does not implement the prescribed fault *handling* matrix beyond generic `parse_soap_fault`.

**Recommendation:** Make filter configurable; on inbound, fault if filter present and unsupported.

---

## Medium

### 9. Unsupported SOAP actions use `text/plain` “OK” (violates §2–3 SOAP expectations, §11.1)

**Code:** [`handle_wsd`](../app/ws_scan.py) default branch and comments describe a “plain OK fallback”.

**Risk:** Violates “SOAP structure valid” for unknown operations on the same endpoint; partners may not parse responses.

**Recommendation:** Return SOAP fault (`InvalidMessage` / `ActionNotSupported` pattern consistent with your stack) instead of plain text for SOAP endpoints.

---

### 10. `ScanAvailableEvent` notification ack — **Resolved** {#10-scanavailableevent-notification-ack--resolved}

**Spec:** Notifications SHOULD be one-way SOAP messages to the event sink in Push mode; the sink HTTP response is implementation-defined for many stacks.

**Implementation:** [`handle_wsd`](../app/ws_scan.py) returns [`build_scan_available_event_ack_response`](../app/ws_scan.py): SOAP 1.2, `Content-Type: application/soap+xml`, `wsa:RelatesTo` matching the notification `wsa:MessageID`, synthetic `ScanAvailableEventResponse` action, empty `soap:Body`. Matches [ws-scan_audit.md](ws-scan_audit.md) Medium #7. Device-driven coverage: Epson WF-3640 on the ScanAvailable → CreateScanJob chain.

**Residual:** Other inbound SOAP actions without a dedicated branch still use `text/plain` “OK” (§9).

---

### 11. XML parsing is regex-based for eventing (violates robustness implied by §11.1)

**Code:** [`app/soap/parsers/eventing.py`](../app/soap/parsers/eventing.py) (`IDENTIFIER_PATTERN`, `EXPIRES_PATTERN`, …), [`app/soap/fault.py`](../app/soap/fault.py) (`parse_soap_fault`), and [`app/ws_scan.py`](../app/ws_scan.py) (`extract_action`, `extract_message_id` via [`app/soap/addressing.py`](../app/soap/addressing.py)) use regex on serialized XML.

**Risk:** Namespace prefix changes, reordering, or wrapping break extraction; wrong `Identifier` match is possible if multiple elements exist.

**Recommendation:** Namespace-aware parsing (ElementTree with explicit URIs) for eventing bodies and headers.

---

### 12. `GetStatus` response does not reflect real expiration (violates §3.5)

**Spec:** MUST return **current** expiration without mutating state.

**Code:** [`build_eventing_get_status_response`](../app/ws_scan.py) always returns `PT1H`.

**Risk:** Misleading status for any peer that polls `GetStatus`.

**Recommendation:** Tie response to stored `expires_at` for the resolved subscription.

---

### 13. `EndTo` duplicates sink address with `NotifyTo`; ReferenceParameters on both (spec nuance / interop)

**Spec:** Minimal profile centers on **Delivery** + **NotifyTo**. `EndTo` is for **SubscriptionEnd** delivery to a manager/sink EPR; it may legitimately differ from `NotifyTo`.

**Code:** [`build_subscribe_request`](../app/ws_eventing_client.py) sets `EndTo` and `NotifyTo` to the same `notify_to` and repeats the same `ReferenceParameters`.

**Risk:** Generally works for Win10-shaped traces (see [`docs/protocol/ws-scan-tcp.md`](../docs/protocol/ws-scan-tcp.md)) but is not the minimal normative shape; some devices may treat `EndTo` strictly.

**Recommendation:** Validate against target devices; optionally omit or specialize `EndTo` per profile.

---

## Low

### 14. Security SHOULDs not addressed (§8)

**Spec:** Authenticate subscribe requests; mitigate third-party subscription abuse.

**Code:** No authentication or sink-ownership validation on [`handle_wsd`](../app/ws_scan.py); outbound subscribe uses anonymous `ReplyTo` (normal) but no auth layer.

**Recommendation:** Document threat model; restrict binding interfaces; optional shared secrets if deployment requires.

---

### 15. Metadata / WSDL (§9) not present

**Spec:** Event source declaration in WSDL (`wse:EventSource="true"`), notification operations, retrievable metadata.

**Code:** No WSDL generation or WS-MetadataExchange surfaced in reviewed modules.

**Recommendation:** If full compliance is a goal, expose metadata or document intentional omission as “minimal device client profile.”

---

### 16. SOAP version coverage (§2.1)

**Spec:** MUST support SOAP 1.1 **and/or** SOAP 1.2.

**Code:** Envelopes use `http://www.w3.org/2003/05/soap-envelope` (SOAP 1.2). No SOAP 1.1 builder.

**Status:** Satisfies “and/or” but not both; note for gateways expecting `text/xml` + SOAP 1.1.

---

### 17. Tests do not assert full spec-level lifecycle or faults

**Code:** [`tests/test_ws_scan.py`](../tests/test_ws_scan.py) checks response action names for eventing operations; [`tests/test_ws_eventing_client.py`](../tests/test_ws_eventing_client.py) exercises subscribe/renew/unsubscribe XML, `parse_renew_response`, and mocked `renew_subscription` / `unsubscribe_from_scanner`; [`tests/test_main_registration.py`](../tests/test_main_registration.py) asserts manager URL + subscription id persistence after registration (maintenance loop stubbed). Still light on end-to-end lease timing, inbound fault mapping, outbound `GetStatus`, and `SubscriptionEnd`.

**Recommendation:** Add contract tests per §11 checklist.

---

## Implemented items (partial credit)

| Requirement area | Evidence |
|------------------|----------|
| Correct primary namespace `http://schemas.xmlsoap.org/ws/2004/08/eventing` | `NS_WSE` in [`app/soap/namespaces.py`](../app/soap/namespaces.py), [`app/ws_scan.py`](../app/ws_scan.py) |
| WS-Addressing headers on outbound `Subscribe` (`Action`, `To`, `MessageID`, `ReplyTo`) | [`build_subscribe_request`](../app/ws_eventing_client.py) |
| Push delivery mode on wire | `Delivery Mode=".../DeliveryModes/Push"` in [`build_subscribe_request`](../app/ws_eventing_client.py) |
| `Subscribe` + `SubscribeResponse` (shapes) | Client + [`build_eventing_subscribe_response`](../app/ws_scan.py) |
| Inbound action dispatch for Renew / GetStatus / Unsubscribe (response shapes only) | [`handle_wsd`](../app/ws_scan.py) |
| Client fault extraction for retry policy | [`parse_soap_fault`](../app/soap/fault.py); `_eventing_registration_loop` in [`main.py`](../main.py) retries via rediscovery/backoff only (no alternate `subscribe_to_url` loop on `wsa:DestinationUnreachable` in the reviewed revision) |
| Store subscription id + manager URL + reference parameters + `Expires` after `Subscribe` / `Renew` | [`app/config.py`](../app/config.py) fields written from [`main.py`](../main.py) `_eventing_registration_loop` / `_eventing_maintenance_loop` |
| Outbound `Renew` + lease scheduling | [`renew_subscription`](../app/ws_eventing_client.py), [`_eventing_maintenance_loop`](../main.py), [`build_renew_request`](../app/soap/builders/eventing.py) |
| Outbound `Unsubscribe` on shutdown and after failed renew | [`_unsubscribe_eventing_best_effort`](../main.py), [`unsubscribe_from_scanner`](../app/ws_eventing_client.py) |
| `ScanAvailableEvent` sink HTTP response (SOAP 1.2 ack) | [`build_scan_available_event_ack_response`](../app/ws_scan.py), [`handle_wsd`](../app/ws_scan.py) |

---

## Suggested remediation order

1. Subscription registry + identifier validation + SOAP faults on server ([`app/ws_scan.py`](../app/ws_scan.py)).
2. `SubscriptionEnd` emission path when local subscription ends unexpectedly; optional outbound `GetStatus` if needed for a deployment profile.
3. Replace regex with namespace-aware XML for eventing parse paths (including manager EPR extraction).
4. Expand pytest coverage to match §11 checklist (renew scheduling, unsubscribe on shutdown, fault paths).

---

*This document is an audit only; it does not change runtime behavior.*
