# 📄 WIA over WSD (WS-Scan) — Client Implementation & Compliance Specification

## 1. Scope

This specification defines requirements for a **client implementation** that interoperates with WSD/WS-Scan devices in a manner compatible with **Windows Image Acquisition (WIA)** behavior.

The client MUST:

* Discover devices via WS-Discovery
* Interact with scanner services via SOAP over HTTP
* Correctly implement WS-Scan operation flows
* Tolerate non-compliant or partially compliant devices

---

## 2. Normative Dependencies

Client MUST support:

* SOAP 1.2
* WS-Addressing (2004/08)
* WS-Discovery
* WS-Scan
* WS-Eventing (OPTIONAL but SHOULD support)

---

## 3. Transport & HTTP Behavior

### 3.1 HTTP Requirements

Client MUST:

* Use HTTP/1.1
* Send `POST` requests for SOAP actions
* Handle:

  * Chunked responses
  * Connection reuse (keep-alive)
  * Premature connection closes

### 3.2 Timeouts

Client MUST:

* Use configurable timeouts
* Default:

  * Connect: ≤ 2s
  * Read: 2–10s

Client MUST retry idempotent operations.

---

## 4. Discovery (WS-Discovery)

### 4.1 Probe Behavior

Client MUST:

* Send multicast `Probe`
* Listen for `ProbeMatch`

### 4.2 Matching Criteria

Client MUST filter for:

```xml
ScannerServiceType
```

### 4.3 XAddr Handling

Client MUST:

* Extract all XAddrs
* Attempt connection in order
* Handle unreachable endpoints gracefully

---

## 5. SOAP Construction Requirements

### 5.1 Envelope Structure

Client MUST generate:

```xml
<soap:Envelope>
  <soap:Header>
    <wsa:Action>...</wsa:Action>
    <wsa:MessageID>uuid:...</wsa:MessageID>
    <wsa:To>...</wsa:To>
  </soap:Header>
  <soap:Body>...</soap:Body>
</soap:Envelope>
```

### 5.2 Header Requirements

| Header    | Requirement                |
| --------- | -------------------------- |
| MessageID | MUST be unique per request |
| Action    | MUST match operation       |
| To        | MUST match endpoint        |
| ReplyTo   | SHOULD be anonymous URI    |

### 5.3 Response Validation

Client MUST:

* Validate `RelatesTo`
* Validate `Action`
* Accept minor deviations (real-world tolerance)

---

## 6. Operation Flow (CRITICAL)

### 6.1 Required Sequence

Client MUST follow this logical sequence:

```
Discovery
  ↓
GetScannerElements
  ↓
CreateScanJob
  ↓
Loop:
   GetJobStatus
   ↓
   If ready → RetrieveImage
```

---

## 7. WS-Scan Operations (Client Behavior)

### 7.1 GetScannerElements

Client MUST:

* Call before any scan job
* Cache capabilities

Client SHOULD:

* Retry on failure
* Handle incomplete responses

---

### 7.2 CreateScanJob

Client MUST:

* Specify:

  * Input source
  * Resolution
  * Format

Client MUST:

* Store returned JobId

Client MUST handle:

* Missing optional fields
* Devices ignoring requested settings

---

### 7.3 GetJobStatus

Client MUST:

* Poll until terminal state

Polling rules:

* Initial interval: 200–500ms
* Backoff up to ~2s

Client MUST handle:

* Missing states
* Devices jumping directly to Completed

---

### 7.4 RetrieveImage

Client MUST:

* Call only when job is ready (or optimistically if device allows)

Client MUST support:

* Base64 inline images
* Large payloads
* Partial/chunked transfers

Client MUST:

* Validate image integrity
* Handle truncated responses with retry

---

### 7.5 CancelJob

Client SHOULD:

* Attempt cancel on:

  * User abort
  * Timeout
  * Error

Client MUST tolerate:

* Devices ignoring cancel

---

## 8. Client State Machine

### 8.1 Internal States

```
Idle
 ↓
Discovered
 ↓
CapabilitiesLoaded
 ↓
JobCreated
 ↓
Polling
 ↓
Retrieving
 ↓
Completed | Error | Cancelled
```

### 8.2 Requirements

Client MUST:

* Track JobId lifecycle
* Prevent invalid transitions
* Clean up abandoned jobs

---

## 9. Error Handling (Client Perspective)

### 9.1 SOAP Faults

Client MUST:

* Parse and classify faults
* Retry where appropriate

### 9.2 Network Failures

Client MUST:

* Retry transient failures
* Abort on persistent failure

### 9.3 Device Misbehavior (COMMON)

Client MUST tolerate:

* Invalid XML
* Missing headers
* Wrong namespaces
* Incorrect states

---

## 10. WIA Compatibility Requirements

### 10.1 Behavioral Expectations

To match Windows:

Client SHOULD:

* Be tolerant, not strict
* Avoid failing on minor spec violations
* Prefer progress over correctness

### 10.2 Retry Behavior

Client MUST:

* Retry:

  * GetJobStatus
  * RetrieveImage
* Limit retries to avoid infinite loops

---

## 11. Performance Constraints

Client SHOULD:

* Avoid excessive polling (<5 req/sec sustained)
* Use backoff strategies
* Cache capabilities

---

## 12. Eventing (Optional)

If implemented:

Client MUST:

* Support Subscribe
* Handle Notify messages

Client SHOULD:

* Fall back to polling if eventing fails

---

## 13. Compliance Checklist (Client-Focused)

### Discovery

* [ ] Sends WS-Discovery Probe
* [ ] Parses ProbeMatch correctly
* [ ] Extracts XAddrs

### SOAP

* [ ] Generates valid SOAP envelopes
* [ ] Uses unique MessageIDs
* [ ] Validates RelatesTo

### Flow

* [ ] Calls GetScannerElements first
* [ ] Creates scan job correctly
* [ ] Polls status correctly
* [ ] Retrieves image only when ready

### Robustness

* [ ] Handles malformed responses
* [ ] Retries transient failures
* [ ] Handles timeouts

### State Management

* [ ] Tracks JobId lifecycle
* [ ] Prevents invalid transitions
* [ ] Cleans up jobs

### Interop

* [ ] Works with at least one real WSD scanner
* [ ] Handles non-compliant devices

---

## 14. Audit Strategy (FOR YOUR USE CASE)

An auditing system SHOULD:

### 14.1 Inspect Outbound Messages

Verify:

* Correct SOAP structure
* Correct WS-Addressing headers
* Correct Action URIs

### 14.2 Validate Sequence

Ensure:

* Correct operation ordering
* No premature RetrieveImage
* Proper polling behavior

### 14.3 Timing Analysis

Check:

* Poll intervals
* Retry behavior
* Timeout handling

### 14.4 Fault Injection

Simulate:

* Invalid SOAP responses
* Dropped connections
* Delayed responses

Verify client resilience.

---

## 15. Real-World Interop Notes (CRITICAL)

Windows-like behavior includes:

* Aggressive retries
* Loose XML parsing
* Ignoring minor protocol violations

Devices often:

* Return incomplete metadata
* Skip states
* Send malformed XML

Your client MUST handle these.

---

## 16. Minimal Viable Client

To be considered compliant:

Client MUST implement:

1. WS-Discovery
2. SOAP messaging with WS-Addressing
3. These operations:

   * GetScannerElements
   * CreateScanJob
   * GetJobStatus
   * RetrieveImage

With:

* Retry logic
* State tracking
* Error handling

---

## 17. Summary

Client compliance is defined by:

> **Correct sequencing + tolerant parsing + resilient networking**

Not strict adherence.

A “perfect” spec implementation will fail in practice—
a **robust, forgiving client** is what matches WIA behavior.
