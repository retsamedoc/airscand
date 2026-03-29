# Common Vendor Quirks in WS-Scan / Windows Image Acquisition

## HP

### **1. Premature “Completed” State**

`GetJobStatus` returns `Completed` BUT image is not yet available

If you immediately call `RetrieveImage`, you may get:

* Empty payload
* SOAP fault
* Connection reset

**Client Requirement**

* Add a **grace retry loop** after `Completed`
* Retry `RetrieveImage` 2–5 times with delay


### **2. Chunked Transfer Instability**

* Uses HTTP chunked encoding
* Occasionally truncates mid-stream

**Client Requirement**

* Detect incomplete image
* Retry `RetrieveImage` (idempotent assumption)


### **3. Ignores Requested DPI**

* Always returns scanner default (e.g., 300 DPI)

**Client Requirement**

* Do NOT assume settings were honored
* Infer actual resolution from image metadata if needed


## Epson

### **1. Strict Parameter Expectations**

* Rejects unknown or optional fields
* SOAP Fault on “extra” XML

**Client Requirement**

* Send **minimal, clean XML**
* Avoid speculative fields

### **2. Requires Exact Namespace Usage**

* Slight namespace mismatch → failure

**Client Requirement**

* Use exact:

  ```
  http://schemas.microsoft.com/windows/2006/08/wdp/scan
  ```

### **3. Slow Job Initialization**

* Long delay after `CreateScanJob`

**Client Requirement**

* Increase polling patience
* Avoid early timeout

### **4. GetJobStatus not supported (WorkForce WF-3640)**

* **Epson WorkForce WF-3640** does not expose a working `GetJobStatus` for the pull scan path (fault or unusable response).

**Client Requirement**

* Do not rely on `GetJobStatus` before `RetrieveImage`; proceed to image retrieval after `CreateScanJob` and use retry/backoff there if needed.

## Canon

### **1. Missing or Invalid Headers**

* Missing `RelatesTo`
* Incorrect `Action`

**Client Requirement**

* Do NOT strictly validate headers
* Match responses heuristically

### **2. Skips Job States**

* Goes:

  ```
  Created → Completed
  ```

  (no Processing)

**Client Requirement**

* Accept missing intermediate states

### **3. Base64 Formatting Issues**

* Line breaks or malformed encoding

**Client Requirement**

* Use tolerant base64 decoding


## Brother


### **1. Requires Polling (No Eventing)**

* WS-Eventing advertised but non-functional

**Client Requirement**

* Always implement polling fallback

### **2. Duplicate Job IDs**

* Same JobId reused occasionally

**Client Requirement**

* Scope JobId per session, not globally

### **3. Delayed Image Availability**

* Similar to HP but longer delay

**Client Requirement**

* Retry `RetrieveImage` longer

## Ricoh

### **1. Large Metadata Payloads**

* `GetScannerElements` returns huge XML

**Client Requirement**

* Handle large XML without failure
* Avoid strict schema validation

### **2. Requires Specific Scan Region Defaults**

* Fails if scan area not defined

**Client Requirement**

* Always include full platen region


## Xerox

### **1. Aggressive Timeouts**

* Drops idle connections quickly

**Client Requirement**

* Avoid long idle periods
* Reconnect as needed

### **2. Partial WS-Scan Implementation**

* Some operations missing or stubbed

**Client Requirement**

* Gracefully degrade features


## Cross-Vendor “Universal” Problems

These happen everywhere:

### 1. Invalid XML

Examples:

* Unclosed tags
* Wrong namespaces
* Encoding issues

**Client MUST**

* Use forgiving XML parser
* Attempt recovery where possible

### 2. Incorrect SOAP Behavior

Examples:

* Wrong `Content-Type`
* Missing SOAP envelope
* HTTP 200 with error body

**Client MUST**

* Not rely solely on HTTP status
* Inspect body content

### 3. Non-Deterministic Timing

* Same device behaves differently per scan

**Client MUST**

* Avoid fixed timing assumptions
* Use adaptive retry/backoff

### 4. Silent Failures

* No response
* Connection drop

**Client MUST**

* Retry safely
* Detect partial progress

## WIA Behavioral Patterns

Windows clients:

* Retry aggressively but quietly
* Ignore minor protocol violations
* Prefer “eventual success” over correctness
* Assume device is wrong, not client

## Recommended Strategies

If you want to pass across all vendors:

### 1. Be Strict in What You Send

* Clean SOAP
* Minimal fields
* Correct namespaces

### 2. Be Extremely Loose in What You Accept

* Broken XML
* Missing headers
* Invalid states

### 3. Treat Everything as Retryable

Except:

* Explicit fatal SOAP faults

### Other Practical Implementation ideas

* **Retry wrapper per operation**
* **State reconciliation layer**
* **Image validation + retry**
* **Timeout + backoff system**
* **Heuristic response matcher (not strict XML binding)**

---

The biggest interoperability unlock:

> **Do not implement WS-Scan as a protocol.
> Implement it as a negotiation with unreliable devices.**
