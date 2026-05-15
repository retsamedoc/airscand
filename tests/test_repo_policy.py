"""Repository policy files (CONTRIBUTING, SECURITY) and README linkage."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def readme_text() -> str:
    """Root README contents."""
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_contributing_md_exists_with_build_commands() -> None:
    """CONTRIBUTING.md exists and documents how to run tests (release hygiene)."""
    path = REPO_ROOT / "CONTRIBUTING.md"
    assert path.is_file(), "CONTRIBUTING.md must exist at repository root"
    text = path.read_text(encoding="utf-8")
    assert "uv run pytest" in text
    assert "ruff" in text
    assert "Conventional Commits" in text


def test_security_md_exists_with_reporting_and_scope() -> None:
    """SECURITY.md exists with reporting channel and trusted-LAN scope."""
    path = REPO_ROOT / "SECURITY.md"
    assert path.is_file(), "SECURITY.md must exist at repository root"
    text = path.read_text(encoding="utf-8")
    assert "Reporting a vulnerability" in text or "report" in text.lower()
    assert "trusted" in text.lower() or "LAN" in text
    assert "github.com/retsamedoc/airscand" in text


def test_readme_links_contributing_and_security(readme_text: str) -> None:
    """README.md links contributors and security reporters to root policy files."""
    assert "CONTRIBUTING.md" in readme_text
    assert "SECURITY.md" in readme_text
