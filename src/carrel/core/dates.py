"""Date parsing for documents: ISO, slashed (`09/10/2026`, `10.09.2026`), textual.

`order` says how to read an ambiguous slashed date: `mdy` (US, the default)
or `dmy` (most of the rest of the world). `find_dates` marks a date as
`ambiguous` when both leading numbers could be a month, so a caller can show
the choice it made. Two-digit years are read as 20xx.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS: dict[str, int] = {}
for _i, _name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"],
    1,
):  # fmt: skip
    MONTHS[_name] = _i
    MONTHS[_name[:3]] = _i
MONTHS["sept"] = 9

_MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
_ISO = re.compile(r"(?<![\d-])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\d-])")
_SLASH = re.compile(
    r"(?<![\d/.-])(?P<a>\d{1,2})(?P<sep>[/.-])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{4}|\d{2})(?![\d/.-])"
)
_YMD = re.compile(r"(?<![\d/.])(?P<y>\d{4})[/.](?P<m>\d{1,2})[/.](?P<d>\d{1,2})(?![\d/.])")
_TEXT_DMY = re.compile(
    rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{_MONTH})\.?,?\s+(?P<y>\d{{4}})\b",
    re.IGNORECASE,
)
_TEXT_MDY = re.compile(
    rf"\b(?P<mon>{_MONTH})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Found:
    value: date
    raw: str
    start: int
    end: int
    ambiguous: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value.isoformat(),
            "raw": self.raw,
            "start": self.start,
            "end": self.end,
            "ambiguous": self.ambiguous,
        }


def _year(y: str) -> int:
    return int(y) if len(y) == 4 else 2000 + int(y)


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _from_slash(m: re.Match[str], order: str) -> tuple[date | None, bool]:
    a, b, y = int(m.group("a")), int(m.group("b")), _year(m.group("y"))
    ambiguous = a <= 12 and b <= 12 and a != b
    if a > 12 and b <= 12:
        return _safe(y, b, a), False  # only d/m works
    if b > 12 and a <= 12:
        return _safe(y, a, b), False  # only m/d works
    month, day = (a, b) if order == "mdy" else (b, a)
    return _safe(y, month, day), ambiguous


def find_dates(text: str, order: str = "mdy") -> list[Found]:
    """Every date in `text`, in order of appearance (ISO, slashed, y/m/d, textual)."""
    if order not in ("mdy", "dmy"):
        raise ValueError("order must be 'mdy' or 'dmy'")
    hits: list[Found] = []
    taken: list[tuple[int, int]] = []

    def add(start: int, end: int, value: date | None, raw: str, ambiguous: bool = False) -> None:
        if value is None or any(s < end and e > start for s, e in taken):
            return
        taken.append((start, end))
        hits.append(Found(value, raw, start, end, ambiguous))

    for m in _ISO.finditer(text):
        add(m.start(), m.end(), _safe(int(m["y"]), int(m["m"]), int(m["d"])), m.group(0))
    for m in _YMD.finditer(text):
        add(m.start(), m.end(), _safe(int(m["y"]), int(m["m"]), int(m["d"])), m.group(0))
    for m in _TEXT_MDY.finditer(text):
        add(
            m.start(),
            m.end(),
            _safe(int(m["y"]), MONTHS[m["mon"].lower()], int(m["d"])),
            m.group(0),
        )
    for m in _TEXT_DMY.finditer(text):
        add(
            m.start(),
            m.end(),
            _safe(int(m["y"]), MONTHS[m["mon"].lower()], int(m["d"])),
            m.group(0),
        )
    for m in _SLASH.finditer(text):
        value, ambiguous = _from_slash(m, order)
        add(m.start(), m.end(), value, m.group(0), ambiguous)
    hits.sort(key=lambda f: f.start)
    return hits


def parse_date(text: str, order: str = "mdy") -> date | None:
    """Parse one date string in full; None when it is not a date."""
    found = find_dates(text.strip(), order)
    if len(found) == 1 and found[0].raw == text.strip():
        return found[0].value
    return None
