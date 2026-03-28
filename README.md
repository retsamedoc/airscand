## airscand

Linux daemon implementing enough of **WSD / WS-Scan** to enable “Scan to Computer” for Epson scanners (starting with WF-3640).

Project status, phase progress, operational checklists, and tested device models / interoperability notes live in [`docs/status.md`](docs/status.md).

### Install dependencies

This project uses **uv** and a project-local virtual environment (`.venv`).

```bash
uv venv
uv sync --extra dev --no-install-project
```

### Run

```bash
WSD_HOST=0.0.0.0 \
WSD_ADVERTISE_ADDR=192.168.1.50 \
uv run python main.py
```

### Commit messages

This repository uses **[Conventional Commits](https://www.conventionalcommits.org/)** for commit subjects (`<type>[(scope)][!]: <description>`).

After cloning, enable the shared hooks and optional editor template (once per clone):

```bash
git config core.hooksPath .githooks
git config commit.template .gitmessage
```

Merge commits, `Revert "…"` messages, and `fixup!` / `squash!` lines from interactive rebase are not validated.

