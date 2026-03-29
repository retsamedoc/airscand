# Configuration

airscand is configured with **environment variables** only. Defaults are chosen for local development; production or headless hosts should set at least **`WSD_ADVERTISE_ADDR`** and **`WSD_OUTPUT_DIR`**.

## Core networking and HTTP

| Variable | Default | Description |
|----------|---------|-------------|
| `WSD_HOST` | `0.0.0.0` | Address the HTTP server binds to. |
| `WSD_PORT` | `5357` | TCP port for SOAP (`WSD_ENDPOINT`) and upload (`WSD_SCAN_PATH`). |
| `WSD_ENDPOINT` | `/wsd` | Path for WS-Scan / event-sink SOAP (`POST`). |
| `WSD_SCAN_PATH` | `/scan` | Path for direct scan upload (`POST`). |
| `WSD_ADVERTISE_ADDR` | *(see below)* | Hostname or IP published in WS-Discovery `XAddrs`. **Set this to an address the printer can use** to reach this machine. |

If `WSD_ADVERTISE_ADDR` is unset or empty, the daemon uses `WSD_HOST` when it is not `0.0.0.0`; otherwise it attempts a best-effort LAN IP detection, falling back to `127.0.0.1`.

## Output and identity

| Variable | Default | Description |
|----------|---------|-------------|
| `WSD_OUTPUT_DIR` | `./scans` | Directory where retrieved scan files are written. Must exist or be creatable by the process. |
| `WSD_UUID` | *(persisted)* | Stable device UUID for discovery. If unset, a UUID is generated once and stored under `XDG_STATE_HOME` (typically `~/.local/state/airscand/uuid`). |

## Scanner discovery and WS-Eventing

| Variable | Default | Description |
|----------|---------|-------------|
| `WSD_SCANNER_XADDR` | *(empty)* | Optional full scanner base URL (e.g. device service URL). If empty, the daemon learns the scanner via WS-Discovery `ProbeMatches`. |
| `WSD_SCANNER_SUBSCRIBE_TO_URL` | *(empty)* | Optional explicit WS-Eventing **Subscribe** target URL. If set, overrides the auto-derived URL (often `http://<scanner>/WDP/SCAN` on supported models). |
| `WSD_EVENTING_PREFLIGHT_GET` | `true` | When true, performs WS-Transfer **Get** before **Subscribe**. Set to `0`/`false`/`no`/`off` to disable (sometimes useful while debugging). |
| `WSD_EVENTING_NOTIFY_TO_URL` | *(empty)* | Optional callback URL for `NotifyTo` / `EndTo` in outbound **Subscribe**. If empty, the daemon builds a URL from `WSD_ADVERTISE_ADDR`, `WSD_PORT`, and `WSD_ENDPOINT`. |
| `WSD_EVENTING_SUBSCRIPTION_ID` | *(empty)* | Rarely needed; optional subscription identifier override. |
| `WSD_EVENTING_SUBSCRIPTION_ID_STATUS` | *(empty)* | Optional identifier for the secondary **ScannerStatusSummary** subscription. |
| `WSD_SUBSCRIBE_DESTINATION_TOKEN` | *(empty)* | If set, forces use of this destination token until registration clears it. |

## Discovery announcements (Hello)

| Variable | Default | Description |
|----------|---------|-------------|
| `WSD_HELLO_INTERVAL_SEC` | `60` | Seconds between multicast **Hello** messages. Use `0` to send a single Hello at startup. |
| `WSD_METADATA_VERSION` | `1` | `MetadataVersion` in discovery metadata. |
| `WSD_APP_SEQUENCE_INSTANCE_ID` | `1` | `InstanceId` on Hello `AppSequence`. |
| `WSD_APP_SEQUENCE_SEQUENCE_ID` | *(persisted)* | `SequenceId` on Hello `AppSequence`. If unset, a value is stored under `XDG_STATE_HOME` (e.g. `~/.local/state/airscand/ws_discovery_sequence_id`). |

## Scan chain behavior

| Variable | Default | Description |
|----------|---------|-------------|
| `WSD_SCANNER_PROFILE` | `epson_wf_3640` | Quirks profile key (e.g. `generic` for protocol-default behavior, `epson_wf_3640` for tested WorkForce behavior). See `docs/protocol/vendor_quirks.md` in the repo. |
| `WSD_RETRIEVE_IMAGE_TIMEOUT_SEC` | *(profile)* | Overrides the profile’s **RetrieveImage** read timeout (seconds). |
| `WSD_CREATE_SCAN_JOB_RETRY_INVALID_DESTINATION_TOKEN` | `true` | When true, may retry **CreateScanJob** without a destination token after `ClientErrorInvalidDestinationToken`. |
| `WSD_WAIT_SCANNER_IDLE_AFTER_RETRIEVE` | `true` | Wait for idle-related status after **RetrieveImage** when supported. |
| `WSD_SCANNER_IDLE_WAIT_SEC` | `60` | Timeout (seconds) for that idle wait. |

## Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `WSD_LOG_LEVEL` | `INFO` | Root log level (`DEBUG`, `INFO`, …). |
| `WSD_LOG_JSON` | `false` | Structured JSON logging when truthy. |
| `WSD_LOG_WRAP` | `true` | Wrap human-readable log lines (non-JSON). |
| `WSD_LOG_WRAP_WIDTH` | `120` | Wrap width; minimum effective width is 40. |

`NO_COLOR` in the environment disables ANSI color in human-readable logs when supported.

## Example: minimal production-style settings

```bash
export WSD_HOST=0.0.0.0
export WSD_ADVERTISE_ADDR=192.168.1.50
export WSD_OUTPUT_DIR=/var/lib/airscand/scans
export WSD_LOG_LEVEL=INFO
```

For more behavior detail, see `docs/status.md` and `docs/design.md` in the repository.
