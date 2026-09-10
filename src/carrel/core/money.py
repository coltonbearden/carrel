"""Money parsing for documents: `$1,234.56`, `1.234,56 €`, `(123.45)`, `123.45-`, `EUR 12`.

Pure Python over `decimal.Decimal`; no locale machinery. The rules are the
ones accounting documents actually follow:

- A currency marker is a symbol (`$ € £ ¥ ₹`) or an ISO code (`USD`, `EUR`, …)
  before or after the number.
- Both `,` and `.` may be thousands or decimal separators. When both appear,
  the last one is the decimal separator. When only one appears once and is
  followed by exactly two digits it is the decimal separator; otherwise it
  groups thousands. A space or apostrophe between 3-digit groups also groups.
- Negative: a leading minus, parentheses `(123.45)`, a trailing minus or a
  trailing `CR` (credit) mark.

`find_amounts` only reports numbers that look like money — a currency marker,
a decimal part or thousands grouping — so bare integers such as years, page
numbers and quantities are left alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_MINUS = "-\u2212"  # hyphen-minus and the typographic minus sign
SYMBOLS: dict[str, str] = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}
CODES: tuple[str, ...] = (
    "USD", "EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "INR", "MXN", "SEK", "NOK", "DKK",
    "PLN", "CZK", "NZD", "ZAR", "BRL", "CNY", "HKD", "SGD",
)  # fmt: skip

_SYM = "[$€£¥₹]"
_CODE = "(?:" + "|".join(CODES) + ")"
_NUMBER = r"\d{1,3}(?:[ ,.'\u2019]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_AMOUNT = re.compile(
    rf"(?:(?P<paren>\()\s*)?"
    rf"(?:(?P<cur1>{_SYM}|{_CODE}\b)\s?)?"
    rf"(?:(?P<sign>[-+\u2212])\s?)?"
    rf"(?P<num>{_NUMBER})"
    rf"(?:\s?(?P<cur2>{_SYM}|\b{_CODE}\b))?"
    rf"(?P<trail>-|\s?(?:CR|DR)\b)?"
    rf"(?P<close>\))?",
    re.IGNORECASE,
)
_GROUP_SEP = re.compile(r"(?<=\d)[ '\u2019](?=\d{3}\b)")


@dataclass(frozen=True)
class Amount:
    value: Decimal
    currency: str | None
    raw: str
    start: int
    end: int

    def as_dict(self) -> dict[str, object]:
        return {
            "value": str(self.value),
            "currency": self.currency,
            "raw": self.raw,
            "start": self.start,
            "end": self.end,
        }


def parse_number(text: str) -> Decimal | None:
    """`1,234.56` / `1.234,56` / `1 234,56` / `1234` → Decimal, or None when it is not a number."""
    s = _GROUP_SEP.sub("", text.strip())
    if not re.fullmatch(r"[-+\u2212]?\d[\d.,]*", s):
        return None
    sign = -1 if s[0] in _MINUS else 1
    s = s.lstrip("-+" + _MINUS)
    commas, dots = s.count(","), s.count(".")
    if commas and dots:
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, ".")
    elif commas or dots:
        sep = "," if commas else "."
        parts = s.split(sep)
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = parts[0] + "." + parts[1]
        elif all(len(p) == 3 for p in parts[1:]) and parts[0] and len(parts[0]) <= 3:
            s = "".join(parts)
        else:
            return None
    try:
        return sign * Decimal(s)
    except InvalidOperation:
        return None


def _currency(*markers: str | None) -> str | None:
    for marker in markers:
        if not marker:
            continue
        marker = marker.strip()
        if marker in SYMBOLS:
            return SYMBOLS[marker]
        return marker.upper()
    return None


def _to_amount(m: re.Match[str]) -> Amount | None:
    value = parse_number(m.group("num"))
    if value is None:
        return None
    negative = bool(m.group("sign") and m.group("sign") in _MINUS)
    trail = (m.group("trail") or "").strip().upper()
    if trail in ("-", "CR") or (m.group("paren") and m.group("close")):
        negative = True
    if negative:
        value = -value
    return Amount(
        value, _currency(m.group("cur1"), m.group("cur2")), m.group(0).strip(), m.start(), m.end()
    )


def parse_amount(text: str) -> Amount | None:
    """Parse one amount string in full (`$1,234.56`, `(12.00)`, `EUR 5`); None when it is not one."""
    m = _AMOUNT.fullmatch(text.strip())
    if not m:
        return None
    return _to_amount(m)


def _money_like(m: re.Match[str]) -> bool:
    num = m.group("num")
    return bool(m.group("cur1") or m.group("cur2") or re.search(r"[.,' \u2019]", num))


def find_amounts(text: str) -> list[Amount]:
    """Every money-looking amount in `text`, in order of appearance."""
    out: list[Amount] = []
    for m in _AMOUNT.finditer(text):
        if not _money_like(m):
            continue
        # a number glued to more digits/letters (e.g. inside an id) is not an amount
        before = text[m.start() - 1] if m.start() > 0 else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if before.isalnum() or after.isalnum() or before in "-/" or after in "-/":
            continue
        amount = _to_amount(m)
        if amount is not None:
            out.append(amount)
    return out
