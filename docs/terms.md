# Glossary

Short definitions for acronyms used in airscand and in this manual. For normative references to specifications, see [References](references.md).

## Web services and transport

| Term | Meaning |
|------|---------|
| **DPWS** | Devices Profile for Web Services. Profiles WSD and related bindings for devices. |
| **MTOM** | SOAP Message Transmission Optimization Mechanism. Sends SOAP with binary parts as MIME multipart (used for **RetrieveImage** payloads). |
| **SOAP** | Simple Object Access Protocol. XML message format used for WSD, WS-Eventing, and WS-Scan traffic in this project. |
| **WSD** | Web Services Dynamic Discovery. Multicast discovery (typically UDP port 3702) so devices and clients find each other’s endpoints. |
| **WS-Eventing** | Subscription protocol used so the scanner can deliver **ScanAvailableEvent** and status events to this host. |
| **WS-Scan** | Microsoft’s web-services scan protocol; job negotiation and image transfer with the scanner often use the **`/WDP/SCAN`** endpoint. |
| **WS-Transfer** | Retrieve resource representations; used here for optional preflight **Get** toward the scanner. |
| **XOP** | XML-binary Optimized Packaging. Pairs with MTOM to reference binary parts from SOAP (e.g. **xop:Include** / `cid:`). |

## Windows-centric names (protocol heritage)

| Term | Meaning |
|------|---------|
| **WDP** | Web Services for Devices **Print** stack naming; Epson devices often expose **`/WDP/SCAN`** for WS-Scan. |
| **WIA** | Windows Image Acquisition. Vendor documentation and capture behavior are often described in WIA terms even when the wire protocol is WS-Scan over WSD. |
