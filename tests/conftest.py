"""Shared pytest plumbing for carrel tests.

Provides (per specs/14-fixtures.md):
- ``fixtures``   — session fixture: Path to tests/fixtures
- ``needs(name)``— skip decorator for tests needing an optional binary,
                   backed by carrel.core.adapters.have(); use as @needs("pandoc")
- ``tmp_copy``   — fixture: callable copying a named fixture into tmp_path
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from carrel.core import adapters

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    """Path to the generated fixture directory (tests/fixtures)."""
    return FIXTURES_DIR


def needs(name: str) -> pytest.MarkDecorator:
    """Skip a test when the adapter's binary is absent: @needs("pandoc")."""
    adapter = adapters.ADAPTERS[name]
    return pytest.mark.skipif(
        not adapters.have(name),
        reason=f"requires '{name}' — {adapter.install_hint}",
    )


def bash_path() -> str | None:
    """Path to a bash that runs scripts, or None.

    On Windows `shutil.which("bash")` finds the WSL launcher stub in System32
    first, which prints an install prompt instead of running anything. Prefer
    Git for Windows' bash — the one Claude Code itself uses for hooks there.
    """
    if os.name != "nt":
        return shutil.which("bash")
    bases = (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMW6432"), r"C:\Program Files")
    for base in bases:
        if not base:
            continue
        for rel in ("Git/bin/bash.exe", "Git/usr/bin/bash.exe"):
            candidate = Path(base) / rel
            if candidate.is_file():
                return str(candidate)
    found = shutil.which("bash")
    if found and "system32" in found.lower():
        return None
    return found


needs_bash = pytest.mark.skipif(bash_path() is None, reason="bash not installed")


@pytest.fixture
def tmp_copy(tmp_path: Path):
    """Copy a fixture (by name) into tmp_path; returns the new Path."""

    def _copy(name: str, new_name: str | None = None) -> Path:
        src = FIXTURES_DIR / name
        dst = tmp_path / (new_name or name)
        shutil.copy2(src, dst)
        return dst

    return _copy
