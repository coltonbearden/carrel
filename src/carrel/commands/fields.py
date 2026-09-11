"""carrel fields — pull vendor, invoice number, dates and totals out of documents.

Heuristic, label-driven extraction over the text every other command reads
(`core.textextract`), for invoices, receipts and statements: `Invoice Date:`,
`Due Date:`, `Subtotal`, `Tax`, `Total Due` and friends are looked up as line
labels; amounts and dates are parsed by `core.money` / `core.dates`; reference
numbers (invoice, PO, IBAN, account) come from `core.patterns`. Every field
carries a confidence: `high` when it followed its label, `medium` when a
heuristic chose it (largest amount = total, first date = date), `low` for a
fallback such as the file's mtime. `--save` writes the fields into the desk
(`carrel meta`, source `fields`); `--set` overrides a value by hand.

`extract_fields()` is the library entry point (MCP `carrel_fields`, `rename`,
`intake`).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import click

from carrel.core import dates, money
from carrel.core import patterns as pat
from carrel.core.adapters import MissingDependencyError
from carrel.core.db import DeskDB
from carrel.core.output import CarrelInputError, ExitCode, emit, fail, handled, progress, root_of
from carrel.core.textextract import extract_text

PROFILES: tuple[str, ...] = ("auto", "invoice", "receipt", "statement")
FIELDS: tuple[str, ...] = (
    "vendor",
    "invoice_no",
    "po",
    "date",
    "due",
    "subtotal",
    "tax",
    "total",
    "currency",
    "iban",
    "account_last4",
)
KINDS: dict[str, str] = {
    "subtotal": "num",
    "tax": "num",
    "total": "num",
    "date": "date",
    "due": "date",
}

# label phrases per field, most specific first; matched at the start of a line
_LABELS: dict[str, tuple[str, ...]] = {
    "total": (
        "total due",
        "amount due",
        "balance due",
        "grand total",
        "total amount",
        "amount payable",
        "total paid",
        "invoice total",
        "total",
        "amount",
    ),
    "subtotal": ("subtotal", "sub-total", "sub total", "net amount", "net"),
    "tax": ("sales tax", "tax", "vat", "gst", "hst", "mwst", "tva", "iva"),
    "date": (
        "invoice date",
        "date of issue",
        "issue date",
        "transaction date",
        "statement date",
        "receipt date",
        "order date",
        "date",
    ),
    "due": ("due date", "payment due", "due by", "pay by", "due"),
}
_LABEL_RE: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    field: [
        (
            label,
            re.compile(
                # `-` counts as a separator only when whitespace follows: in
                # `Total Due  -$1,234.56` the dash belongs to the amount
                r"^\s*"
                + re.escape(label)
                + r"\b\s*(?:\([^)]*\))?\s*(?:[:.]|-(?=\s))?\s*(?P<rest>.*)$",
                re.IGNORECASE,
            ),
        )
        for label in labels
    ]
    for field, labels in _LABELS.items()
}
# Payment terms, not an amount: `Net 30` yes, `Net  500.00` (a subtotal line) no.
_NET_TERMS = re.compile(r"\bnet\s+(\d{1,3})\b(?![\d.,])", re.IGNORECASE)
MAX_NET_DAYS = 180
_PROFILE_WORDS: dict[str, tuple[str, ...]] = {
    "invoice": ("invoice", "inv #", "bill to", "amount due", "purchase order"),
    "receipt": (
        "receipt",
        "change due",
        "cashier",
        "thank you for",
        "paid",
        "tender",
        "card ending",
    ),
    "statement": (
        "statement",
        "opening balance",
        "closing balance",
        "account summary",
        "statement period",
    ),
}
_HEADING_WORDS = {"invoice", "receipt", "statement", "tax invoice", "bill", "order"}


def _field(value: str, confidence: str, evidence: str | None) -> dict[str, Any]:
    return {"value": value, "confidence": confidence, "evidence": (evidence or "").strip()[:120]}


def detect_profile(text: str) -> str:
    low = text.lower()
    scores = {
        name: sum(low.count(word) for word in words) for name, words in _PROFILE_WORDS.items()
    }
    best = max(scores, key=lambda k: (scores[k], k == "invoice"))
    return best if scores[best] else "invoice"


def _labelled(lines: list[str], field: str) -> list[tuple[str, str]]:
    """Every (remainder, evidence line) whose line starts with one of the field's labels.

    All of them, not just the first: a document can carry a decoy above the
    real line (`Tax ID: 12-3456789` before `Tax  $84.56`, `Total units 3.00`
    before `Total  $1,234.56`), and the caller decides which candidate actually
    parses into a value.
    """
    out: list[tuple[str, str]] = []
    for _label, rx in _LABEL_RE[field]:
        for i, line in enumerate(lines):
            m = rx.match(line)
            if not m:
                continue
            rest = m.group("rest").strip()
            if not rest and i + 1 < len(lines):  # label on its own line: value follows
                out.append((lines[i + 1].strip(), f"{line.strip()} / {lines[i + 1].strip()}"))
            elif rest:
                out.append((rest, line))
    return out


def _best_amount(candidates: list[tuple[str, str]]) -> tuple[money.Amount, str] | None:
    """The amount a labelled line states, preferring one that carries a currency marker.

    `Total units          3.00` and `Total          $1,234.56` both match the
    `total` label; the one with a currency symbol is the money line, and a later
    line beats an earlier one because totals sit at the foot of a document.
    """
    best: tuple[tuple[int, int], money.Amount, str] | None = None
    for rank, (text, evidence) in enumerate(candidates):
        found = money.find_amounts(text)
        if not found:
            continue
        amount = found[-1]  # "Total ..... $1,234.56": the value ends the line
        score = (1 if amount.currency else 0, rank)
        if best is None or score > best[0]:
            best = (score, amount, evidence)
    return (best[1], best[2]) if best else None


def _first_date(candidates: list[tuple[str, str]], order: str) -> tuple[dates.Found, str] | None:
    for text, evidence in candidates:
        found = dates.find_dates(text, order)
        if found:
            return found[0], evidence
    return None


_GREETING = re.compile(
    r"^(?:hello|hi|hey|dear|good (?:morning|afternoon|evening))\b", re.IGNORECASE
)
_MAIL_FROM = re.compile(
    r"^From:\s*(?:\"?(?P<name>[^\"<]+?)\"?\s*<[^>]+>|(?P<addr>[^\s<>]+@[^\s<>]+))\s*$"
)


def _vendor(lines: list[str]) -> tuple[str, str, str] | None:
    """(name, evidence, confidence): an email's From display name, else the first name-like line."""
    for line in lines[:3]:
        m = _MAIL_FROM.match(line.strip())
        if m:
            name = (m.group("name") or m.group("addr").split("@")[1]).strip()
            return name[:80], line, "high"
    for line in lines[:12]:
        s = line.strip()
        if len(s) < 3 or sum(ch.isalpha() for ch in s) < 3 or s.endswith(","):
            continue
        low = s.lower()
        if _GREETING.match(s) or low in _HEADING_WORDS:
            continue
        if any(low.startswith(lbl) for lbls in _LABELS.values() for lbl in lbls):
            continue
        if re.search(r"\d{3,}", s) or "@" in s or "http" in low or ":" in s:
            continue
        return s[:80], line, "medium"
    return None


def extract_fields(
    source: Path | str,
    *,
    profile: str = "auto",
    date_order: str = "mdy",
    ocr: bool = False,
    text: str | None = None,
) -> dict[str, Any]:
    """Fields for one document: {path, profile, fields: {name: {value, confidence, evidence}}}.

    `source` is a file (text comes from `extract_text`, honouring `ocr`); pass
    `text` to reuse a body that was already extracted — the file's mtime and
    name still back the low-confidence fallbacks. A `source` that is not a file
    is treated as a label only. Amounts are canonical decimal
    strings, dates ISO. Only fields that were found are present.
    """
    if profile not in PROFILES:
        raise CarrelInputError(f"unknown profile {profile!r} (choose from: {', '.join(PROFILES)})")
    if date_order not in ("mdy", "dmy"):
        raise CarrelInputError("date_order must be 'mdy' or 'dmy'")
    candidate = Path(source)
    path: Path | None = candidate if candidate.exists() else None
    if path is None and text is None:
        raise CarrelInputError(f"no such file: {source}")
    body = text if text is not None else extract_text(candidate, ocr=ocr)
    lines = [ln for ln in body.splitlines() if ln.strip()]
    kind = detect_profile(body) if profile == "auto" else profile
    out: dict[str, dict[str, Any]] = {}

    # -- amounts -----------------------------------------------------------
    all_amounts = money.find_amounts(body)
    for name in ("total", "subtotal", "tax"):
        money_hit = _best_amount(_labelled(lines, name))
        if money_hit is not None:
            out[name] = _field(str(money_hit[0].value), "high", money_hit[1])
    if "total" not in out and all_amounts:
        largest = max(all_amounts, key=lambda a: abs(a.value))
        out["total"] = _field(str(largest.value), "medium", largest.raw)
    currencies = [a.currency for a in all_amounts if a.currency]
    if currencies:
        counts = Counter(currencies)
        # most frequent, then alphabetical: identical input gives an identical answer
        best = min(counts, key=lambda code: (-counts[code], code))
        out["currency"] = _field(best, "high" if "total" in out else "medium", best)

    # -- dates -------------------------------------------------------------
    all_dates = dates.find_dates(body, date_order)
    for name in ("date", "due"):
        date_hit = _first_date(_labelled(lines, name), date_order)
        if date_hit is not None:
            out[name] = _field(date_hit[0].value.isoformat(), "high", date_hit[1])
    if "date" not in out and all_dates:
        out["date"] = _field(all_dates[0].value.isoformat(), "medium", all_dates[0].raw)
    if "date" not in out and path is not None and path.exists():
        stamp = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
        out["date"] = _field(stamp, "low", "file mtime")
    if "due" not in out and "date" in out:
        terms = _NET_TERMS.search(body)
        if terms and int(terms.group(1)) <= MAX_NET_DAYS:
            base = date.fromisoformat(out["date"]["value"])
            due = base + timedelta(days=int(terms.group(1)))
            out["due"] = _field(due.isoformat(), "medium", terms.group(0))

    # -- references --------------------------------------------------------
    refs = pat.find_refs(body, [pat.PATTERNS[k] for k in ("invoice", "po", "iban", "account")])
    by_kind: dict[str, dict[str, Any]] = {}
    for r in refs:
        by_kind.setdefault(r["kind"], r)
    if "invoice" in by_kind:
        out["invoice_no"] = _field(by_kind["invoice"]["value"], "high", by_kind["invoice"]["value"])
    if "po" in by_kind:
        out["po"] = _field(by_kind["po"]["value"], "high", by_kind["po"]["value"])
    if "iban" in by_kind:
        out["iban"] = _field(by_kind["iban"]["value"], "high", by_kind["iban"]["value"])
    if "account" in by_kind:
        digits = re.sub(r"\D", "", by_kind["account"]["value"])
        if len(digits) >= 4:
            out["account_last4"] = _field(digits[-4:], "high", by_kind["account"]["value"])

    # -- vendor ------------------------------------------------------------
    vendor = _vendor(lines)
    if vendor:
        out["vendor"] = _field(vendor[0], vendor[2], vendor[1])
    elif path is not None:
        out["vendor"] = _field(path.stem, "low", "file name")

    ordered = {name: out[name] for name in FIELDS if name in out}
    return {"path": str(path) if path is not None else None, "profile": kind, "fields": ordered}


def parse_overrides(overrides: Sequence[str]) -> list[tuple[str, str]]:
    """`FIELD=VALUE` specs → (field, value) pairs; raises CarrelInputError for a bad spec."""
    out: list[tuple[str, str]] = []
    for spec in overrides:
        name, sep, value = spec.partition("=")
        name = name.strip().lower()
        if not sep or name not in FIELDS:
            raise CarrelInputError(
                f"--set expects FIELD=VALUE with FIELD one of {', '.join(FIELDS)} (got: {spec!r})"
            )
        out.append((name, value.strip()))
    return out


def apply_overrides(record: dict[str, Any], overrides: Sequence[str]) -> None:
    """`name=value` pairs replace extracted fields (confidence `user`)."""
    for name, value in parse_overrides(overrides):
        record["fields"][name] = _field(value, "user", "--set")
    record["fields"] = {n: record["fields"][n] for n in FIELDS if n in record["fields"]}


def save_fields(
    db: DeskDB, path: Path, record: dict[str, Any], *, source: str = "fields"
) -> list[str]:
    """Write the record's fields into the desk (num/date kinds where they apply); returns the keys."""
    keys: list[str] = []
    for name, info in record["fields"].items():
        try:
            db.set_meta(path, name, info["value"], kind=KINDS.get(name), source=source)
        except CarrelInputError:
            db.set_meta(path, name, info["value"], kind="str", source=source)
        keys.append(name)
    return keys


def fields_for(
    paths: Sequence[Path | str],
    *,
    profile: str = "auto",
    date_order: str = "mdy",
    ocr: bool = False,
    overrides: Sequence[str] = (),
    save_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """One record per file (directories walked like `refs`); failures are per-file records."""
    from carrel.commands.refs import candidate_files

    parse_overrides(overrides)  # a bad --set fails before any file is read
    targets = candidate_files(
        [Path(p) for p in paths], ocr=ocr, root=Path(save_root).resolve() if save_root else None
    )
    ctx = click.get_current_context(silent=True)
    records: list[dict[str, Any]] = []
    for f in targets:
        progress(f"fields: {f}", ctx)
        try:
            record = extract_fields(f, profile=profile, date_order=date_order, ocr=ocr)
            apply_overrides(record, overrides)
        except MissingDependencyError as e:
            record = {
                "path": str(f),
                "profile": None,
                "fields": {},
                "error": str(e),
                "kind": "missing_dependency",
            }
        except CarrelInputError as e:
            record = {
                "path": str(f),
                "profile": None,
                "fields": {},
                "error": str(e),
                "kind": "bad_input",
            }
        except Exception as e:  # noqa: BLE001 — one unreadable file is a record, never an abort
            record = {
                "path": str(f),
                "profile": None,
                "fields": {},
                "error": f"{e.__class__.__name__}: {e}",
                "kind": "error",
            }
        records.append(record)
    if save_root is not None:
        to_save = [r for r in records if r["fields"]]
        if to_save:
            with DeskDB(save_root) as db:
                for record in to_save:
                    record["saved"] = save_fields(db, Path(record["path"]).resolve(), record)
    return records


def _human(records: list[dict[str, Any]]) -> None:
    for rec in records:
        click.echo(f"{rec['path']}  ({rec.get('profile') or '?'})")
        if rec.get("error"):
            click.echo(f"  error: {rec['error']}", err=True)
            continue
        if not rec["fields"]:
            click.echo("  (no fields found)")
            continue
        width = max(len(n) for n in rec["fields"])
        for name, info in rec["fields"].items():
            click.echo(
                f"  {name:<{width}}  {info['value']:<24} {info['confidence']:<6} {info['evidence']}"
            )
        if rec.get("saved"):
            click.echo(f"  saved: {', '.join(rec['saved'])}")


@click.command(name="fields")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "--profile",
    type=click.Choice(PROFILES),
    default="auto",
    show_default=True,
    help="Document kind; auto picks by keywords.",
)
@click.option(
    "--date-order",
    type=click.Choice(["mdy", "dmy"]),
    default="mdy",
    show_default=True,
    help="How to read an ambiguous slashed date such as 03/04/2026.",
)
@click.option(
    "--ocr", is_flag=True, help="OCR images and scanned PDFs (needs tesseract / ocrmypdf)."
)
@click.option(
    "--set",
    "overrides",
    multiple=True,
    metavar="FIELD=VALUE",
    help="Override an extracted field (repeatable).",
)
@click.option(
    "--save", is_flag=True, help="Write the fields into the desk db under --root (source: fields)."
)
@click.option("--fail-empty", is_flag=True, help="Exit 5 when no file yielded any field.")
@click.pass_context
@handled
def cmd(
    ctx: click.Context,
    paths: tuple[Path, ...],
    profile: str,
    date_order: str,
    ocr: bool,
    overrides: tuple[str, ...],
    save: bool,
    fail_empty: bool,
) -> None:
    """Extract vendor, invoice number, dates and totals from PATH... (invoices, receipts, statements).

    Directories are walked like `refs`. Fields: vendor, invoice_no, po, date,
    due, subtotal, tax, total, currency, iban, account_last4 — each with a
    confidence (high: after its label; medium: heuristic; low: fallback) and
    the evidence line. Amounts are plain decimals, dates ISO. JSON output is a
    list of {path, profile, fields: {name: {value, confidence, evidence}}}.
    """
    try:
        records = fields_for(
            list(paths),
            profile=profile,
            date_order=date_order,
            ocr=ocr,
            overrides=overrides,
            save_root=root_of(ctx) if save else None,
        )
    except CarrelInputError as e:
        if "--set" in str(e):
            raise click.UsageError(str(e)) from e
        raise
    emit(ctx, records, human=_human)
    missing = [r for r in records if r.get("kind") == "missing_dependency"]
    if missing and len(missing) == len(records):
        fail(
            f"nothing extracted — {len(missing)} file(s) need a missing tool:\n{missing[0]['error']}",
            ExitCode.MISSING_DEP,
        )
    if fail_empty and not any(r["fields"] for r in records):
        fail("no fields found (--fail-empty)", ExitCode.EMPTY)
