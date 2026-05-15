# Security policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| Latest commit on `main` | Yes |
| Tagged releases (`v0.0.x`) | Best effort; use latest tag for deployments |

There is no separate LTS branch. Security fixes land on `main` and are included in the next patch tag.

## Reporting a vulnerability

**Please do not open a public GitHub issue** for security vulnerabilities.

1. Use **[GitHub private vulnerability reporting](https://github.com/retsamedoc/airscand/security/advisories/new)** for this repository, **or**
2. Email the maintainer listed in [`LICENSE`](LICENSE) with a clear description, steps to reproduce, and impact assessment.

We aim to acknowledge reports within **7 days** and to coordinate disclosure once a fix is available. If you need encrypted communication, say so in your initial report and we will arrange a channel.

## Threat model and scope

airscand is designed for a **trusted local area network** (home or office LAN where the operator controls both the scanner and the scan host). See [`docs/design.md`](docs/design.md) non-goals: **authentication and transport security are out of scope** for the MVP.

### In scope for this project

- Bugs that let an **untrusted network participant** trigger scans, overwrite arbitrary files, or crash the daemon remotely.
- **Memory exhaustion** or unbounded disk writes via `/scan` or SOAP endpoints without operator intent.
- **XML/SOAP parsing** issues that lead to denial of service on the scan host.

### Out of scope (by design)

- **TLS / HTTPS** for WS-Scan or WS-Discovery (devices use plain HTTP on the LAN).
- **Subscriber authentication** for WS-Eventing (no shared secret or cert pinning today).
- Protecting the daemon from a **malicious LAN insider** with full network access—deploy on segmented networks or firewalls if that is a requirement.
- Physical access, compromised printer firmware, or attacks on the printer itself.

### Operational guidance

- Bind only to interfaces you intend (`WSD_HOST`, `WSD_ADVERTISE_ADDR`; see [`docs/configuration.md`](docs/configuration.md)).
- Run the daemon as a **dedicated user** with write access limited to `WSD_OUTPUT_DIR`.
- Do not expose ports **5357** (HTTP) or **3702** (WS-Discovery UDP) to the public Internet without additional controls.

## Safe harbor

We appreciate responsible disclosure. Reporters acting in good faith, following this policy, will not be asked to pursue legal action for research limited to demonstrating impact on their own equipment or with explicit permission.

## Security-related development

When changing HTTP/SOAP handlers or file persistence, add tests that cover **failure paths** and **size limits** where applicable. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for build/test commands.
