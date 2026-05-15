# Specifications index

Normative protocol and audit material for **airscand** lives under **`docs/`**, not in this directory. Use this file as a single entry point for humans and tooling.

## Protocol and design

| Topic | Path |
|-------|------|
| Product design and non-goals | [`docs/design.md`](../docs/design.md) |
| Architecture and package map | [`docs/architecture.md`](../docs/architecture.md) |
| Configuration (env vars) | [`docs/configuration.md`](../docs/configuration.md) |
| WS-Scan over TCP | [`docs/protocol/ws-scan-tcp.md`](../docs/protocol/ws-scan-tcp.md) |
| WIA client expectations | [`docs/protocol/wia_client_spec.md`](../docs/protocol/wia_client_spec.md) |
| Vendor quirks | [`docs/protocol/vendor_quirks.md`](../docs/protocol/vendor_quirks.md) |

## Compliance audits

| Area | Path |
|------|------|
| WS-Scan (Microsoft element docs) | [`docs/ws-scan_audit.md`](../docs/ws-scan_audit.md) |
| WS-Eventing | [`docs/ws-eventing_audit.md`](../docs/ws-eventing_audit.md) |
| WIA client flow | [`docs/wia_client_audit.md`](../docs/wia_client_audit.md) |

## Backlog and status

| Topic | Path |
|-------|------|
| Living implementation backlog | [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md) |
| Phase status | [`docs/status.md`](../docs/status.md) |
| Roadmap | [`docs/ROADMAP.md`](../docs/ROADMAP.md) |

## Contract tests (pytest)

Audit-aligned modules map test names to audit sections:

- `tests/test_ws_eventing_audit_compliance.py` → `docs/ws-eventing_audit.md` §17
- `tests/test_ws_scan_audit_compliance.py` → `docs/ws-scan_audit.md` (resolved items and documented gaps)
