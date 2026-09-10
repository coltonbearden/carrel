"""Unit tests for carrel.core.patterns (spec 23): kinds, validators, find_refs, redact sharing."""

from __future__ import annotations

import pytest

from carrel.commands.redact import BUILTINS, Rule, _redact_text
from carrel.core import patterns as pat
from carrel.core.output import CarrelInputError

# ----------------------------------------------------------------- validators


def _iban(country: str, bban: str) -> str:
    """Build a valid IBAN by computing its check digits."""
    body = bban + country + "00"
    numeric = "".join(str(int(ch, 36)) for ch in body)
    check = 98 - int(numeric) % 97
    return f"{country}{check:02d}{bban}"


@pytest.mark.parametrize(
    ("fn", "good", "bad"),
    [
        (pat.luhn_valid, "4111111111111111", "4111111111111112"),
        (pat.cc_valid, "4111 1111 1111 1111", "4111 1111 1111 1112"),
        (pat.iban_valid, _iban("DE", "370400440532013000"), "DE89370400440532013001"),
        (pat.iban_valid, "GB82 WEST 1234 5698 7654 32", "GB82 WEST 1234 5698 7654 33"),
        (pat.aba_valid, "021000021", "021000022"),
        (pat.isbn_valid, "0-306-40615-2", "0-306-40615-3"),
        (pat.isbn_valid, "978-0-306-40615-7", "978-0-306-40615-8"),
        (pat.gtin_valid, "4006381333931", "4006381333932"),
        (pat.gtin_valid, "96385074", "96385075"),
    ],
)
def test_validators(fn, good, bad):
    assert fn(good) is True
    assert fn(bad) is False


def test_iban_length_table_rejects_wrong_length():
    assert pat.iban_valid("DE" + "00" + "3704004405320130") is False  # 20 chars, DE needs 22
    assert pat.aba_valid("991000021") is False  # bad prefix even if the checksum held
    assert pat.isbn_valid("12345") is False
    assert pat.gtin_valid("123") is False


# ---------------------------------------------------------------- registry


def test_registry_groups_and_defaults():
    assert list(pat.PATTERNS)[:5] == ["email", "phone", "ssn", "ipv4", "cc"]
    assert set(pat.GROUPS) == {p.group for p in pat.PATTERNS.values()}
    assert pat.kinds("pii") == ["email", "phone", "ssn", "ipv4", "cc"]
    default = [p.name for p in pat.resolve_kinds(None)]
    assert default == list(pat.REFERENCE_KINDS)
    assert "email" not in default and "invoice" in default and "iban" in default


def test_resolve_kinds_dedupes_and_rejects_unknown():
    chosen = pat.resolve_kinds(["Invoice", " iban ", "invoice", ""])
    assert [p.name for p in chosen] == ["invoice", "iban"]
    with pytest.raises(CarrelInputError, match="unknown kind 'dna'"):
        pat.resolve_kinds(["dna"])


def test_parse_extra():
    extra = pat.parse_extra("acme=ACME-(?P<v1>\\d+)")
    assert extra.name == "acme" and extra.group == "reference"
    (m,) = list(extra.finditer("ref ACME-42 today"))
    assert extra.value(m) == "42" and extra.span(m) == (9, 11)
    for bad in ("noequals", "=x", "Bad Name=x", "ok=("):
        with pytest.raises(CarrelInputError):
            pat.parse_extra(bad)


@pytest.mark.parametrize(
    ("kind", "text", "value"),
    [
        ("invoice", "Invoice # INV-2026-0042", "INV-2026-0042"),
        ("invoice", "invoice no. 12345 due", "12345"),
        ("invoice", "see INV/2026/7 attached", "INV/2026/7"),
        ("po", "PO# 4471", "4471"),
        ("po", "Purchase Order: PO-88", "PO-88"),
        ("order", "Order No. 88-771", "88-771"),
        ("check", "Check # 1044", "1044"),
        ("account", "Account number ****1234", "****1234"),
        ("tracking", "Tracking #: 1Z999AA10123456784", "1Z999AA10123456784"),
        ("ticket", "case ABC-1234 opened", "ABC-1234"),
        ("iban", "IBAN DE89 3704 0044 0532 0130 00.", "DE89370400440532013000"),
        ("routing", "routing 021000021", "021000021"),
        ("ein", "EIN 12-3456789", "12-3456789"),
        ("vat", "VAT number: GB123456789", "GB123456789"),
        ("isbn", "ISBN 978-0-306-40615-7", "978-0-306-40615-7"),
        ("gtin", "EAN 4006381333931", "4006381333931"),
        ("doi", "doi:10.1000/xyz123.", "10.1000/xyz123"),
        ("ups", "1z999aa10123456784", "1Z999AA10123456784"),
        ("usps", "9400111899223197428490", "9400111899223197428490"),
    ],
)
def test_each_kind_finds_its_value(kind, text, value):
    rows = pat.find_refs(text, [pat.PATTERNS[kind]])
    assert [(r["kind"], r["value"]) for r in rows] == [(kind, value)]


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("invoice", "Invoice Date: 2026-09-10"),  # label followed by a word without digits
        ("invoice", "invoices 12"),
        ("po", "PO Box 1234"),
        ("order", "in order to 12"),  # no label word
        ("ticket", "INV-2026-0042"),  # not a ticket: known prefix + more segments
        ("iban", "DE89 3704 0044 0532 0130 01"),  # wrong check digits
        ("routing", "123456789"),  # checksum fails
        ("routing", "2026-021000021"),  # part of a longer dashed number
        ("isbn", "ISBN 0-306-40615-3"),
        ("gtin", "EAN 4006381333932"),
        ("vat", "GB123456789"),  # no label
    ],
)
def test_negatives(kind, text):
    assert pat.find_refs(text, [pat.PATTERNS[kind]]) == []


def test_find_refs_counts_pages_and_lines():
    text = "Invoice # A-1\nline two INV-9\n\fpage two mentions INV-9 and invoice A-1 again\nINV-9\n"
    rows = pat.find_refs(text, [pat.PATTERNS["invoice"]])
    by_value = {r["value"]: r for r in rows}
    assert by_value["INV-9"] == {
        "kind": "invoice",
        "value": "INV-9",
        "count": 3,
        "valid": None,
        "pages": [1, 2],
        "lines": [2, 3, 4],
    }
    assert by_value["A-1"]["pages"] == [1, 2] and by_value["A-1"]["count"] == 2
    assert [r["value"] for r in rows] == ["A-1", "INV-9"]  # first occurrence order


def test_find_refs_default_kinds_and_validity_flag():
    rows = pat.find_refs("iban GB82 WEST 1234 5698 7654 32 ticket QA-77 mail a@b.co")
    kinds = {r["kind"]: r for r in rows}
    assert kinds["iban"]["valid"] is True
    assert kinds["ticket"]["valid"] is None
    assert "email" not in kinds  # pii only when asked for


def test_find_refs_caps_locations():
    text = "\n".join(f"case QA-{n}" for n in [77] * 30)
    (row,) = pat.find_refs(text, [pat.PATTERNS["ticket"]], max_locations=5)
    assert row["count"] == 30 and len(row["lines"]) == 5


# ------------------------------------------------------------ redact sharing


def test_redact_builtins_are_the_registry():
    assert list(BUILTINS) == list(pat.PATTERNS)


def test_redact_label_driven_kind_keeps_the_label():
    rule = Rule("invoice", BUILTINS["invoice"].compiled(), BUILTINS["invoice"])
    out, counts = _redact_text("Invoice # INV-2026-0042 and INV-7 paid", [rule], "█")
    assert out == "Invoice # █ and █ paid"
    assert counts == {"invoice": 2}


def test_redact_validator_still_rejects_bad_check_digits():
    rule = Rule("iban", BUILTINS["iban"].compiled(), BUILTINS["iban"])
    text = "good GB82WEST12345698765432 bad GB82WEST12345698765433"
    out, counts = _redact_text(text, [rule], "X")
    assert out == "good X bad GB82WEST12345698765433" and counts == {"iban": 1}
