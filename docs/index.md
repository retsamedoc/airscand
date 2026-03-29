# airscand

**airscand** is a Linux daemon that implements enough of **WS-Discovery (WSD)** and **WS-Scan** for your network scanner—especially Epson WorkForce models—to treat this computer as a **Scan to Computer** destination, without proprietary Windows or macOS software.

This site is the **user manual**: how to install, configure, and fix common issues. Deeper protocol notes and design detail live alongside these pages in the same documentation tree.

## What you get

- **Discovery:** The daemon advertises itself on the LAN so the printer can find your host.
- **Registration:** Outbound WS-Eventing subscription so the scanner lists your PC as a destination.
- **Scanning:** When you start a scan from the device, the daemon negotiates the job and saves images under a directory you configure.

## Where to go next

| Topic | Page |
|--------|------|
| Install and first run in a few minutes | [Getting started](getting-started.md) |
| Environment variables and behavior | [Configuration](configuration.md) |
| When something does not work | [Troubleshooting](troubleshooting.md) |
| Acronyms (SOAP, WSD, MTOM, …) | [Glossary](terms.md) |
| Tests, lint, CI, building docs | [Development](development.md) |
| Goals, phases, and protocol intent | [Design specification](design.md) |
| Modules and runtime structure (source of truth) | [Architecture diagram](architecture.md) |

## Scope and assumptions

airscand targets a **trusted home or office LAN**. It does not implement full WS-* compliance, authentication, or a graphical UI. Tested devices include **Epson WF-3640** and **Epson WF-3760**; other models may work with profile tweaks—see [Configuration](configuration.md) and [Troubleshooting](troubleshooting.md).
