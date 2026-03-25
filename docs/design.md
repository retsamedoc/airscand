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
|CreateScanJob	| Initiate scan job| 
|Behavior | Return minimal valid SOAP responses| 
Provide JobId |Direct printer to scan upload endpoint|


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
- Printer sends CreateScanJob to /wsd
- Daemon responds with job metadata

### 6.3 Image Transfer

Two possible modes:

#### Push Model (expected)
- Printer POSTs image to /scan

#### Pull Model (fallback)
- Daemon calls RetrieveImage

### 7. Phased Development Plan
#### Phase 0 — Baseline Setup
- Project scaffolding
- Logging + config

##### Success Criteria
- Service starts cleanly

#### Phase 1 — Discovery (Early Win)
- Implement Probe listener
- Send ProbeMatch

##### Success Criteria
- Printer recognizes daemon OR sends HTTP requests

#### Phase 2 — HTTP Endpoint
- Start HTTP server
- Log SOAP requests

##### Success Criteria
- SOAP requests observed

#### Phase 3 — WS-Scan Basics
- Handle CreateScanJob
- Return minimal response

##### Success Criteria
- Printer proceeds without error

#### Phase 4 — Image Capture (Core Goal)
- Implement /scan
- Save files

##### Success Criteria

- Scanned image saved to disk

#### Phase 5 — Eventing (Conditional)
- Implement WS-Eventing if required

##### Success Criteria
- Scan button reliably triggers workflow

#### Phase 6 — Hardening
- XML parsing
- Error handling
- State management

#### Phase 7 — Packaging
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
- Does the printer require WS-Eventing?
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
