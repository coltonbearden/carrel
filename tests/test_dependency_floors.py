"""The runtime floors D-026 raised for security, held so a revert cannot pass quietly.

Found reviewing #64 (`pypdf>=6.19.0`): no test read the specifier. Putting it
back to `>=6.18.1`, or to `>=5.0`, left `uv lock --check` and the whole suite
green, because the version `uv.lock` pins satisfies any lower floor. The same
review found the floor restated by hand in the changelog and two other
documents, two of them already stale.

The rules fail closed: a floor written in a form this module cannot read is an
error, not a pass.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Per parser of untrusted input, the oldest release that carries its newest
#: advisory fix. Raise an entry together with the floor; never lower one (D-026).
SECURITY_FLOORS = {"pypdf": "6.19.0"}


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _declared_floor(name: str) -> str:
    """The `X.Y.Z` of `name>=X.Y.Z` in `[project].dependencies`."""
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lines = [dep for dep in project["dependencies"] if re.match(rf"{re.escape(name)}\b", dep)]
    assert len(lines) == 1, f"expected one runtime requirement on {name}, found {lines}"
    match = re.fullmatch(rf"{re.escape(name)}\s*>=\s*(\d+(?:\.\d+)*)", lines[0])
    assert match, f"{lines[0]!r} is not a plain `>=` floor; teach this test to read it"
    return match.group(1)


@pytest.mark.parametrize(("name", "minimum"), sorted(SECURITY_FLOORS.items()))
def test_a_security_floor_is_never_lowered(name: str, minimum: str):
    floor = _declared_floor(name)
    assert _version(floor) >= _version(minimum), (
        f"pyproject.toml declares {name}>={floor}, below {minimum}: `pip install carrel` "
        "would keep a release with a known advisory (D-026)"
    )


@pytest.mark.parametrize("name", sorted(SECURITY_FLOORS))
@pytest.mark.skipif(
    not (REPO_ROOT / "uv.lock").is_file(), reason="uv.lock is not part of the sdist"
)
def test_no_security_floor_is_above_what_ci_tests(name: str):
    """CI installs `uv.lock`, so a floor above the locked version is untested."""
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = [p["version"] for p in lock["package"] if p["name"] == name]
    assert len(locked) == 1, f"uv.lock must pin exactly one {name}, found {locked}"
    floor = _declared_floor(name)
    assert _version(floor) <= _version(locked[0]), (
        f"{name}>={floor} is above the {locked[0]} that uv.lock pins and CI tests"
    )


@pytest.mark.parametrize("name", sorted(SECURITY_FLOORS))
@pytest.mark.skipif(
    not (REPO_ROOT / "CHANGELOG.md").is_file(), reason="CHANGELOG.md is not in this tree"
)
def test_the_changelog_states_the_floor_pyproject_declares(name: str):
    """The newest entry that names the floor is the one users read; it is typed by hand."""
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    stated = re.search(rf"requires `{re.escape(name)}>=(\d+(?:\.\d+)*)`", text)
    assert stated, f"CHANGELOG.md no longer says which {name} carrel requires"
    floor = _declared_floor(name)
    assert stated.group(1) == floor, (
        f"CHANGELOG.md's newest entry says {name}>={stated.group(1)}, "
        f"pyproject.toml declares >={floor}"
    )
