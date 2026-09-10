"""Shared pattern library: PII strings and reference numbers, with check digits.

One registry feeds two commands. `carrel redact --builtin NAME` replaces the
matched value; `carrel refs` reports every distinct value it finds (and can tag
the files that carry it). Keeping them together means a kind added here — an
IBAN, a routing number, a PO number — is redactable and findable at once.

Three groups:

- ``pii``: email, phone, ssn, ipv4, cc — the v0.1 redact builtins, unchanged.
- ``reference``: label-driven document references (invoice, po, order, check,
  account, tracking, ticket). They need a label such as "Invoice #" nearby,
  because a bare run of digits means nothing; the value group is what is
  reported and redacted, never the label.
- ``identifier``: self-describing codes (iban, routing, ein, vat, isbn, gtin,
  doi, ups, usps). Where a check digit exists the validator enforces it, so a
  nine-digit number is only a routing number when the ABA checksum holds.

A pattern's regex may carry named groups ``v1``, ``v2``, … for alternatives;
the first one that matched is the value. Patterns without such a group use
the whole match (the pii kinds). Validators receive the normalised value.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from typing import Any

from carrel.core.output import CarrelInputError

GROUPS: tuple[str, ...] = ("pii", "reference", "identifier")

_VALUE_GROUPS = ("v1", "v2", "v3")
_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


# ------------------------------------------------------------------ validators


def luhn_valid(digits: str) -> bool:
    """Luhn checksum over a digit string (payment cards, some account numbers)."""
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def cc_valid(value: str) -> bool:
    digits = re.sub(r"[ -]", "", value)
    return 13 <= len(digits) <= 19 and luhn_valid(digits)


# IBAN lengths per country (ISO 13616 registry, the commonly seen entries).
IBAN_LENGTHS: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22,
    "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18, "FR": 27,
    "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28,
    "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19,
    "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24, "PL": 28, "PS": 29,
    "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SE": 24, "SI": 19, "SK": 24,
    "SM": 27, "TN": 24, "TR": 26, "UA": 29, "VG": 24, "XK": 20,
}  # fmt: skip


def iban_valid(value: str) -> bool:
    """ISO 7064 mod-97 check plus the registered length for known countries."""
    s = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    expected = IBAN_LENGTHS.get(s[:2])
    if expected is not None and len(s) != expected:
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


_ABA_PREFIXES = {*range(13), *range(21, 33), *range(61, 73), 80}


def aba_valid(value: str) -> bool:
    """ABA routing number: 9 digits, 3-7-1 weighted checksum, valid Federal Reserve prefix."""
    if not re.fullmatch(r"\d{9}", value):
        return False
    d = [int(c) for c in value]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    return total % 10 == 0 and int(value[:2]) in _ABA_PREFIXES


def isbn_valid(value: str) -> bool:
    """ISBN-10 (mod 11, X = 10) or ISBN-13 (EAN weights 1/3)."""
    s = re.sub(r"[\s-]", "", value).upper()
    if len(s) == 10 and re.fullmatch(r"\d{9}[\dX]", s):
        total = sum((10 - i) * (10 if ch == "X" else int(ch)) for i, ch in enumerate(s))
        return total % 11 == 0
    if len(s) == 13 and s.isdigit():
        return gtin_valid(s)
    return False


def gtin_valid(value: str) -> bool:
    """GTIN-8/12/13/14 (EAN/UPC) mod-10 check digit, weights 3/1 from the right."""
    if not value.isdigit() or len(value) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in value]
    payload, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    return (10 - total % 10) % 10 == check


# -------------------------------------------------------------------- registry


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: str
    group: str
    purpose: str
    validator: Callable[[str], bool] | None = None
    normalize: Callable[[str], str] | None = None
    flags: int = 0

    def compiled(self) -> re.Pattern[str]:
        return _compile(self.regex, self.flags)

    def _value_group(self, m: re.Match[str]) -> str | None:
        for name in _VALUE_GROUPS:
            if name in m.re.groupindex and m.group(name) is not None:
                return name
        return None

    def span(self, m: re.Match[str]) -> tuple[int, int]:
        """Character span of the value (the label, when any, stays untouched)."""
        name = self._value_group(m)
        return m.span(name) if name else m.span()

    def value(self, m: re.Match[str]) -> str:
        name = self._value_group(m)
        raw = m.group(name) if name else m.group(0)
        return self.normalize(raw) if self.normalize else raw

    def accepts(self, m: re.Match[str]) -> bool:
        return self.validator is None or self.validator(self.value(m))

    def finditer(self, text: str) -> Iterator[re.Match[str]]:
        for m in self.compiled().finditer(text):
            if self.accepts(m):
                yield m


@cache
def _compile(regex: str, flags: int) -> re.Pattern[str]:
    return re.compile(regex, flags)


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _upper(value: str) -> str:
    return value.strip().upper()


def _strip_doi(value: str) -> str:
    return value.rstrip(".,;:)]}'\"")


# A value word that contains at least one digit (so "Invoice Date" never yields "Date").
_DIGIT_WORD = r"(?=[A-Z0-9/-]*\d)[A-Z0-9][A-Z0-9/-]{1,30}"
_LABEL = r"(?:\s+(?:number|num|no|nr|id)\.?)?(?:\s*[:#])*\s*"
_STRICT_LABEL = r"(?:\s+(?:number|num|no|nr|id)\.?|\s*#)(?:\s*[:#])*\s*"


def _p(
    name: str,
    regex: str,
    group: str,
    purpose: str,
    *,
    validator: Callable[[str], bool] | None = None,
    normalize: Callable[[str], str] | None = None,
    flags: int = 0,
) -> Pattern:
    return Pattern(name, regex, group, purpose, validator, normalize, flags)


PATTERNS: dict[str, Pattern] = {
    p.name: p
    for p in [
        # -- pii (the original redact builtins; regexes unchanged) -------------
        _p("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "pii", "email addresses"),
        _p(
            "phone",
            r"(?<!\d)(?:\+?1[-. ])?(?:\(\d{3}\)[-. ]?|\d{3}[-. ])\d{3}[-. ]\d{4}(?!\d)",
            "pii",
            "North American phone numbers",
        ),
        _p("ssn", r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)", "pii", "US social security numbers"),
        _p(
            "ipv4",
            r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)",
            "pii",
            "IPv4 addresses",
        ),
        _p(
            "cc",
            r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)",
            "pii",
            "payment card numbers (Luhn-checked)",
            validator=cc_valid,
        ),
        # -- reference (label-driven) -------------------------------------------
        _p(
            "invoice",
            r"\b(?P<v1>INV[-/]?\d[A-Z0-9/-]*)\b"
            r"|\b(?:invoice|inv)\.?" + _LABEL + r"(?P<v2>" + _DIGIT_WORD + r")\b",
            "reference",
            "invoice numbers (INV-…, or after an 'Invoice #' label)",
            normalize=_upper,
            flags=re.IGNORECASE,
        ),
        _p(
            "po",
            r"\b(?P<v1>PO[-/]\d[A-Z0-9/-]*)\b"
            r"|\b(?:P\.?O\.?|purchase\s+order)" + _LABEL + r"(?P<v2>" + _DIGIT_WORD + r")\b",
            "reference",
            "purchase order numbers (PO-…, or after a 'PO #' label)",
            normalize=_upper,
            flags=re.IGNORECASE,
        ),
        _p(
            "order",
            r"\border" + _STRICT_LABEL + r"(?P<v1>" + _DIGIT_WORD + r")\b",
            "reference",
            "order numbers (after an 'Order #' / 'Order No.' label)",
            normalize=_upper,
            flags=re.IGNORECASE,
        ),
        _p(
            "check",
            r"\b(?:check|cheque|chk)" + _STRICT_LABEL + r"(?P<v1>\d{3,12})\b",
            "reference",
            "check numbers (after a 'Check #' label)",
            flags=re.IGNORECASE,
        ),
        _p(
            "account",
            r"\b(?:account|acct|a/c)\.?" + _STRICT_LABEL + r"(?P<v1>[\dX*•-]{4,34})\b",
            "reference",
            "account numbers, possibly masked (after an 'Account #' label)",
            normalize=_upper,
            flags=re.IGNORECASE,
        ),
        _p(
            "tracking",
            r"\btracking" + _LABEL + r"(?P<v1>[A-Z0-9]{8,34})\b",
            "reference",
            "carrier tracking numbers (after a 'Tracking #' label)",
            normalize=_upper,
            flags=re.IGNORECASE,
        ),
        _p(
            "ticket",
            r"\b(?!(?:INV|PO)-)(?P<v1>[A-Z]{2,6}-\d{2,6})\b(?![-/]\d)",
            "reference",
            "ticket / case ids like ABC-1234",
        ),
        # -- identifier (self-describing; check digits where they exist) --------
        _p(
            "iban",
            r"\b(?P<v1>[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?)\b",
            "identifier",
            "IBANs (mod-97 checked)",
            validator=iban_valid,
            normalize=_squash,
        ),
        _p(
            "routing",
            r"(?<![\d-])(?P<v1>\d{9})(?![\d-])",
            "identifier",
            "US ABA routing numbers (checksum + prefix checked)",
            validator=aba_valid,
        ),
        _p(
            "ein",
            r"(?<![\d-])(?P<v1>\d{2}-\d{7})(?![\d-])",
            "identifier",
            "US employer identification numbers (NN-NNNNNNN)",
        ),
        _p(
            "vat",
            r"\b(?:VAT|USt[-. ]?Id(?:Nr)?|TVA|IVA|BTW|MwSt)\.?"
            r"(?:\s+(?:number|num|no|nr|id|reg(?:istration)?)\.?)?(?:\s*[:#])*\s*"
            r"(?P<v1>[A-Z]{2}\s?[A-Z0-9]{8,12})\b",
            "identifier",
            "VAT registration numbers (after a 'VAT' label)",
            normalize=_squash,
            flags=re.IGNORECASE,
        ),
        _p(
            "isbn",
            r"\bISBN(?:-1[03])?\s*[:#]?\s*(?P<v1>\d[\d -]{8,16}[\dX])\b",
            "identifier",
            "ISBN-10/13 (check digit verified)",
            validator=isbn_valid,
            normalize=_squash,
            flags=re.IGNORECASE,
        ),
        _p(
            "gtin",
            r"\b(?:GTIN|EAN|UPC|barcode)(?:-?1[2348])?\s*[:#]?\s*(?P<v1>\d{8}|\d{12,14})\b",
            "identifier",
            "GTIN / EAN / UPC barcodes (check digit verified)",
            validator=gtin_valid,
            flags=re.IGNORECASE,
        ),
        _p(
            "doi",
            r"\b(?P<v1>10\.\d{4,9}/[^\s\"<>]+)",
            "identifier",
            "DOIs",
            normalize=_strip_doi,
        ),
        _p(
            "ups",
            r"\b(?P<v1>1Z[A-Z0-9]{16})\b",
            "identifier",
            "UPS tracking numbers (1Z…)",
            normalize=_upper,
            flags=re.IGNORECASE,
        ),
        _p(
            "usps",
            r"(?<!\d)(?P<v1>9[0-5]\d{18}(?:\d{2})?)(?!\d)",
            "identifier",
            "USPS tracking numbers (20/22 digits starting 9x)",
        ),
    ]
}


def kinds(group: str | None = None) -> list[str]:
    """Registered kind names, optionally restricted to one group."""
    return [p.name for p in PATTERNS.values() if group is None or p.group == group]


REFERENCE_KINDS: tuple[str, ...] = tuple(kinds("reference") + kinds("identifier"))


def parse_extra(spec: str) -> Pattern:
    """`NAME=REGEX` → an ad-hoc reference pattern (a `v1` group, if any, is the value)."""
    name, sep, regex = spec.partition("=")
    name = name.strip().lower()
    if not sep or not regex:
        raise CarrelInputError(f"--pattern expects NAME=REGEX (got: {spec!r})")
    if not _NAME_RE.match(name):
        raise CarrelInputError(f"bad pattern name {name!r}: use [a-z][a-z0-9_-]*")
    try:
        re.compile(regex)
    except re.error as e:
        raise CarrelInputError(f"bad --pattern {name!r}: {e}") from e
    return Pattern(name, regex, "reference", f"custom pattern {name}")


def resolve_kinds(requested: Iterable[str] | None) -> list[Pattern]:
    """Patterns for the requested kind names (default: reference + identifier kinds)."""
    if requested is None:
        return [PATTERNS[k] for k in REFERENCE_KINDS]
    out: list[Pattern] = []
    for name in requested:
        key = name.strip().lower()
        if not key:
            continue
        if key not in PATTERNS:
            raise CarrelInputError(f"unknown kind {name!r} (choose from: {', '.join(PATTERNS)})")
        if PATTERNS[key] not in out:
            out.append(PATTERNS[key])
    return out


def find_refs(
    text: str,
    patterns: Iterable[Pattern] | None = None,
    *,
    max_locations: int = 20,
) -> list[dict[str, Any]]:
    """Distinct values per kind in `text`, with counts and where they occur.

    Pages are counted from form feeds (pdftotext separates pages with ``\\f``),
    so a plain text file is one page; lines are 1-based within the whole text.
    Rows come back in registry order, then by first occurrence.
    """
    chosen = list(patterns) if patterns is not None else resolve_kinds(None)
    # offsets of every page break / newline, computed once: a match's page and
    # line are then a bisect, not a rescan of the text (a 50k-line export with a
    # hit per line stays linear)
    feeds = [m.start() for m in re.finditer("\f", text)]
    newlines = [m.start() for m in re.finditer("\n", text)]
    found: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for pattern in chosen:
        for m in pattern.finditer(text):
            value = pattern.value(m)
            key = (pattern.name, value)
            row = found.get(key)
            if row is None:
                row = {
                    "kind": pattern.name,
                    "value": value,
                    "count": 0,
                    "valid": True if pattern.validator is not None else None,
                    "pages": set(),
                    "lines": set(),
                }
                found[key] = row
                order.append(key)
            row["count"] += 1
            start = m.start()
            row["pages"].add(bisect_right(feeds, start - 1) + 1)
            row["lines"].add(bisect_right(newlines, start - 1) + 1)
    return [
        {
            **row,
            "pages": sorted(row["pages"])[:max_locations],
            "lines": sorted(row["lines"])[:max_locations],
        }
        for row in (found[k] for k in order)
    ]
