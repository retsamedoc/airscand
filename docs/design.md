# WSD / WS-Scan Linux Daemon for Epson Scanner Integration
## 1. Overview

This project implements a Linux-based daemon that enables “Scan to Computer” functionality for the Epson WorkForce WF-3640 without relying on proprietary Windows/macOS software.

The daemon emulates the behavior of Epson Event Manager by implementing:
- **WS-Discovery (WSD)** for device discovery
- **WS-Scan** for scan job negotiation
- **HTTP endpoints** for scan data transfer

The system is designed to be:
- Modular and testable
- Configurable via environment variables
- Observable via structured logging
- Extensible toward production/container deployment

## 2. Goals

### Primary Goals

- Allow printer to discover a Linux host as a scan destination
- Accept scan jobs initiated from the printer UI
- Receive and persist scanned images to disk
- Operate without proprietary Epson software

### Secondary Goals

- Maintain clean modular architecture
- Support structured logging for observability
- Enable easy containerization (future)
- Provide testable components (unit + integration)

## 3. Non-Goals
- Full WS-* specification compliance
- Multi-printer orchestration
- Authentication/security (assumes trusted network)
- GUI or user-facing interface

## 4. System Architecture

### High-Level Flow

[ Printer ]
    │
    │ (UDP multicast: Probe)
    ▼
[ WSD Discovery Module ]
    │
    │ (ProbeMatch response)
    ▼
[ HTTP SOAP Server ]
    │
    │ (CreateScanJob)
    ▼
[ WS-Scan Handler ]
    │
    │ (image transfer)
    ▼
[ Scan Receiver ]
    │
    ▼
[ File System Storage ]

## 5. Core Components
### 5.1 Discovery Module (discovery.py)

#### Responsibilities
- Listen on UDP multicast 239.255.255.250:3702
- Detect WS-Discovery Probe messages
- Respond with ProbeMatch

#### Key Behaviors
- Advertise endpoint (XAddrs)
- Provide stable UUID identity
- Use correct SOAP + WS-Addressing headers
#### Inputs
- UDP packets (SOAP over UDP)
#### Outputs
- SOAP ProbeMatch responses
#### Risks
- Incorrect namespaces → printer ignores service
- Missing headers → no follow-up communication

### 5.2 HTTP Server (http_server.py)
Responsibilities
- Expose HTTP endpoint (default: port 5357)
- Route SOAP requests and scan uploads

#### Endpoints

|Path|	Purpose|
|---|---------|
|/wsd	| WS-Scan SOAP endpoint |
|/scan	| Image upload endpoint |

#### Technology
- aiohttp (async, lightweight, testable)

### 5.3 SOAP Handling (soap.py)
 #### Responsibilities
- Parse incoming SOAP XML
- Extract:
  - ```wsa:Action```
  - ```wsa:MessageID```
- Generate SOAP responses

#### Implementation Strategy
- Phase 1: string matching
- Phase 2: lxml + XPath

### 5.4 WS-Scan Handler (ws_scan.py)
#### Responsibilities
- Handle scan-related SOAP actions
- Initial Supported Actions

|Action	|Purpose|
|--|--|
|CreateScanJob	| Respond to printer-initiated scan job with **CreateScanJobResponse** (**JobId**, **JobToken**, **ImageInformation**, **DocumentFinalParameters**)|
|ScanAvailableEvent	| Acknowledge with SOAP 1.2 **ScanAvailableEventResponse**; schedule outbound scan chain|


### 5.5 Scan Receiver (scan_receiver.py)
#### Responsibilities
- Receive raw scan data via HTTP POST
- Detect file type (JPG/PDF)
- Persist to disk

#### File Detection Logic

|Signature	|Type|
|-|-|
|FF D8|	JPG|
|%PDF|	PDF|
|other|	BIN|

#### Output
Files stored in configured directory

### 5.6 Configuration (config.py)

#### Strategy
- Environment variable driven

#### Variables
| Variable	| Default	| Description |
|-|-|-|
WSD_HOST	|0.0.0.0	|Bind address
WSD_PORT	|5357	|HTTP port
WSD_ENDPOINT	|/wsd	|SOAP endpoint
WSD_SCAN_PATH	|/scan	|Upload endpoint
WSD_OUTPUT_DIR	|./scans	|Output directory
WSD_UUID	|(generated)	|Persistent identity

#### Notes
 - UUID must persist across restarts

### 5.7 Logging (logging.py)

#### Requirements
 - Structured JSON logs
- Output to stdout/stderr

#### Example Output
```JSON
{
  "level": "INFO",
  "message": "Probe received",
  "module": "discovery"
}
```
## 6. Data Flow

### 6.1 Discovery Phase
- Printer sends Probe
- Daemon receives packet
- Daemon responds with ProbeMatch
- Printer records endpoint

### 6.2 Scan Initiation
- User presses “Scan to Computer”
- Printer sends `ScanAvailableEvent` to `/wsd`
- Daemon responds with HTTP 200 and a SOAP 1.2 envelope (`application/soap+xml`) correlating via `wsa:RelatesTo` to the notification `wsa:MessageID` (**ScanAvailableEventResponse**)
- Daemon submits outbound `GetScannerElements` to scanner `/WDP/SCAN` as best-effort metadata probe for:
  - `ScannerDescription`
  - `DefaultScanTicket`
  - `ScannerConfiguration`
  - `ScannerStatus`
- Metadata probe failures/timeouts are logged but do not stop the chain
- Daemon submits outbound `ValidateScanTicket` to scanner `/WDP/SCAN` using **ScanTicket** from **`resolve_scan_ticket_xml_for_chain`** (inner ticket from **DefaultScanTicket** when the metadata probe succeeded; otherwise a Win10-like template)
- Daemon waits for `ValidateScanTicketResponse`
- If validation succeeds, daemon submits outbound `CreateScanJob` to scanner `/WDP/SCAN` (with **DestinationToken** / **ScanIdentifier** as resolved from subscribe and the event)
- If **CreateScanJob** succeeds with **JobId** and **JobToken**, daemon submits outbound `RetrieveImage` to scanner `/WDP/SCAN`
- `RetrieveImageRequest` fields are mapped as:
  - `JobId`: `CreateScanJobResponse/JobId`
  - `JobToken`: `CreateScanJobResponse/JobToken` only
  - `DocumentDescription`: fixed default value `1`
- `GetScannerElements` payload blocks are currently stored in scan-chain results and structured logs for diagnostics and future ticket synthesis.

### 6.3 Image Transfer

Two possible modes:

#### Push Model (expected)
- Printer POSTs image to /scan

#### Pull Model (fallback)
- Daemon calls `RetrieveImage` to the scanner; the **HTTP response** carries `RetrieveImageResponse` (including image bytes when successful).
- In parallel, the scanner may push **`ScannerStatusSummaryEvent`** notifications to the daemon’s event sink (`NotifyTo`, same path as `ScanAvailableEvent`). Those events carry **global** `ScannerState` (for example **Processing** while the device works, then **Idle** when the scanner is ready again)—they are **not** scoped to a specific `JobId`.
- After a successful `RetrieveImage` HTTP response, the daemon may **wait** for a subsequent **`ScannerStatusSummaryEvent` with `ScannerState` Idle** (configurable timeout) so the pull chain aligns with “scanner returned to idle” before the next `ScanAvailableEvent`. The operator selects the scan destination on the device; `ScanAvailableEvent` is delivered to the subscriber for that destination.

### 7. Phased Development Plan
#### Phase 0 — Baseline Setup
- Project scaffolding
- Logging + config

##### Success Criteria
- Service starts cleanly

#### Phase 1 — Discovery (Preliminary)
- Implement Probe listener
- Send ProbeMatch

##### Success Criteria
- Printer sends Probe and daemon responds with valid ProbeMatch
- Printer records/attempts the advertised endpoint (`XAddrs`)
- Note: this phase alone does not validate end-to-end scan workflow readiness

#### Phase 2 — HTTP + WS-Eventing Registration
- Start HTTP server
- Log SOAP requests
- Implement WS-Eventing registration/subscription handshake required by scanner
- Verify daemon is registered as a scan destination on the device

##### Success Criteria
- SOAP requests are observed on HTTP endpoint(s)
- WS-Eventing registration succeeds and scanner can target daemon as destination
- Status: complete (validated on target Epson workflow)
- Completion date: 2026-03-26
- Tested models: Epson WF-3640

#### Phase 3 — WS-Scan Basics
- Handle CreateScanJob
- Return minimal response

##### Success Criteria
- Printer proceeds without error

#### Phase 4 — Image Capture (Core Goal)
- Implement /scan
- Save files (including device-initiated chain output under configured output directory)

##### Success Criteria

- Scanned image saved to disk
- Status: complete — validated on **Epson WF-3640** (front-panel scan, file under `scans/`, clean run **2026-03-28**)

#### Phase 5 — Hardening
- XML parsing
- Error handling
- State management

#### Phase 6 — Packaging
- Containerization
- CLI
- systemd integration

### 8. Testing Strategy
#### Unit Tests
- SOAP parsing
- File type detection
- Response generation

#### Integration Tests
- Simulated UDP Probe
- Mock SOAP requests

#### Manual Tests
- Restart printer
- Trigger scan
- Observe logs and output files

### 9. Deployment Considerations
#### Current
- Bare metal
- Open network

#### Future
- Docker container
- Kubernetes-compatible
- Health endpoints

### 10. Risks & Mitigations

#### Risk: Proprietary Epson Behavior
- Mitigation: iterative logging + reverse engineering

#### Risk: Strict SOAP Requirements
- Mitigation: gradually increase spec compliance

#### Risk: Discovery Failure
- Mitigation: reuse logic from wsdd

#### Risk: Printer Caching
- Mitigation:
  - Restart printer
  - Rotate UUID (dev only)

### 11. Future Enhancements
- OCR pipeline integration
- Cloud upload (S3, etc.)
- Home automation integration
- Multi-device support
- Authentication support

### 12. Open Questions
- Does it push or require image retrieval?
- Are additional SOAP headers mandatory?

### 13. Summary

This project incrementally builds a Linux-native replacement for Epson Event Manager by:
- Emulating WSD discovery
- Handling WS-Scan job negotiation
- Receiving and storing scan data

The phased approach ensures:

- Early validation (discovery)
- Continuous feedback (logging)
- Gradual complexity increase
