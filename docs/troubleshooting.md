# Troubleshooting

Use this page when the daemon runs but the **printer does not list your PC**, **registration fails**, or **scans do not land on disk**.

## General approach

1. Confirm **Layer 2/3 connectivity**: printer and host on the same LAN or routed path; no client isolation on Wi-Fi blocking device-to-device traffic.
2. Set **`WSD_ADVERTISE_ADDR`** explicitly to the IPv4 address you would use from the printer to reach this host (not `127.0.0.1` unless you truly mean loopback).
3. **Firewall:** allow inbound TCP on **`WSD_PORT`** (default **5357**) from the printer’s IP. Allow **UDP multicast** traffic for WS-Discovery (typically **239.255.255.250:3702**) on the interface that faces the LAN.
4. **Raise logging:** `WSD_LOG_LEVEL=DEBUG` and, for machine parsing, `WSD_LOG_JSON=1`.
5. If all else fails, tcpdump and wireshark are your friends.

## The scanner never shows this computer

| Symptom | Things to check |
|---------|-----------------|
| No Hello / no discovery activity | Verify the process is running; check for bind errors on `WSD_HOST`/`WSD_PORT`. |
| Wrong or unreachable `XAddrs` | Set **`WSD_ADVERTISE_ADDR`** to the printer-reachable IP or hostname. Multi-homed machines often need this. |
| Printer on a different VLAN or guest Wi-Fi | Many APs block station-to-station traffic; move the printer or PC to the main LAN. |

## Registration fails or repeats forever

Outbound registration uses WS-Transfer **Get** (unless disabled) and WS-Eventing **Subscribe** toward the scanner.

| Symptom | Things to check |
|---------|-----------------|
| Logs show scanner endpoint not discovered | Ensure the scanner is on and supports WSD; try **`WSD_SCANNER_XADDR`** with the device’s service URL from vendor docs or discovery tools. |
| Subscribe target wrong for your model | Try **`WSD_SCANNER_SUBSCRIBE_TO_URL`** explicitly (e.g. vendor-specific path). Defaults align with Win10-style **`/WDP/SCAN`** on tested Epson devices. |
| Preflight **Get** causes faults | Set **`WSD_EVENTING_PREFLIGHT_GET=0`** and retry; some firmware behaves better without preflight. |
| **NotifyTo** URL not reachable by printer | Ensure **`WSD_EVENTING_NOTIFY_TO_URL`** (if set) or the built-in URL uses an address and port the scanner can call back—same constraints as `WSD_ADVERTISE_ADDR`. |

Logs mentioning **SubscriptionManager** missing or unsubscribe skipped usually indicate a partial subscription; a resubscribe may occur on the next loop—watch for repeated errors versus one-time warnings.

## Scans start but files are empty or missing

| Symptom | Things to check |
|---------|-----------------|
| Nothing under `WSD_OUTPUT_DIR` | Confirm the directory exists and is writable by the daemon user. |
| Timeouts during **RetrieveImage** | Increase **`WSD_RETRIEVE_IMAGE_TIMEOUT_SEC`**; **`generic`** profile uses a shorter default than **`epson_wf_3640`**. |
| Wrong behavior for your hardware | Try **`WSD_SCANNER_PROFILE=generic`** or another profile documented under `docs/protocol/vendor_quirks.md`. |

## Destination token errors

If **CreateScanJob** fails with invalid destination token messages, the daemon can retry (see **`WSD_CREATE_SCAN_JOB_RETRY_INVALID_DESTINATION_TOKEN`**). If problems persist, capture DEBUG logs around **SubscribeResponse** and **ScanAvailableEvent**—token selection is sensitive to **ClientContext** matching.

## Still stuck

Collect **DEBUG** logs from startup through one failed scan attempt, redact passwords if any, and note **printer model**, **firmware version**, and **exact environment variables** (especially `WSD_ADVERTISE_ADDR`, `WSD_SCANNER_XADDR`, `WSD_SCANNER_SUBSCRIBE_TO_URL`, and profile). Cross-check current milestone behavior in `docs/status.md` in the repo.
