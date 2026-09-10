"""Email parsing shared by textextract, inspect, convert and `carrel mail`.

Everything is stdlib: `email` (RFC 5322 / MIME) for `.eml` and `mailbox` for
`.mbox`. Messages are parsed with `email.policy.default`, which gives header
objects with proper decoding (RFC 2047 subjects, address lists) and
`get_body()` / `iter_attachments()` for MIME trees.

Nothing here writes a message; `carrel mail` writes attachments and split
messages as plain files.
"""

from __future__ import annotations

import mailbox
import re
from collections.abc import Iterator
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

from carrel.core.output import CarrelInputError

_HEADER_LINE = re.compile(rb"^[A-Za-z][A-Za-z0-9-]*:")
_HEADER_FIELDS = (b"From:", b"Date:", b"Subject:", b"Message-ID:", b"Received:", b"To:")
_MBOX_FROM = re.compile(rb"^From \S+ .{20,}\n")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


# ----------------------------------------------------------------- detection


def looks_like_eml(head: bytes) -> bool:
    """RFC 5322 header block at the start: ≥2 well-known fields before the first blank line."""
    seen = 0
    for line in head.split(b"\n", 60):
        stripped = line.rstrip(b"\r")
        if not stripped:
            break
        if not (_HEADER_LINE.match(stripped) or stripped[:1] in (b" ", b"\t")):
            return False
        if any(stripped.lower().startswith(f.lower()) for f in _HEADER_FIELDS):
            seen += 1
    return seen >= 2


def looks_like_mbox(head: bytes) -> bool:
    """A `From sender date` separator line followed by a header block."""
    if not _MBOX_FROM.match(head):
        return False
    rest = head.split(b"\n", 1)[1] if b"\n" in head else b""
    return looks_like_eml(rest)


# ------------------------------------------------------------------- parsing


def parse_eml(path: Path) -> EmailMessage:
    with path.open("rb") as fh:
        return BytesParser(policy=policy.default).parse(fh)


def iter_mbox(path: Path) -> Iterator[EmailMessage]:
    """Messages of an mbox file in order (read-only; the file is never locked or rewritten)."""
    try:
        box = mailbox.mbox(str(path), factory=None, create=False)
    except (OSError, mailbox.Error) as e:
        raise CarrelInputError(f"cannot read mbox {path}: {e}") from e
    try:
        for key in box.iterkeys():
            raw = box.get_bytes(key)
            yield BytesParser(policy=policy.default).parsebytes(raw)
    finally:
        box.close()


def header_date(msg: EmailMessage) -> str | None:
    """The Date header as ISO 8601 (timezone kept), or None when absent/unparseable."""
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(str(raw)).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def addresses(msg: EmailMessage, field: str) -> list[str]:
    """`Name <addr>` strings of an address header (empty when absent)."""
    values = msg.get_all(field, [])
    out: list[str] = []
    for name, addr in getaddresses([str(v) for v in values]):
        if not addr and not name:
            continue
        out.append(f"{name} <{addr}>" if name else addr)
    return out


def message_ids(value: str | None) -> list[str]:
    """Every `<…>` token of a Message-ID / In-Reply-To / References header."""
    return re.findall(r"<[^<>\s]+>", value or "")


def _first_id(value: str | None) -> str | None:
    ids = message_ids(value)
    return ids[0] if ids else None


def body_text(msg: EmailMessage) -> str:
    """Plain body text: the text/plain part, else the text/html part flattened, else ''."""
    from carrel.core.textextract import html_to_text

    try:
        part = msg.get_body(preferencelist=("plain", "html"))
    except Exception:  # noqa: BLE001 — a broken MIME tree yields no body, never a crash
        part = None
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(content, str):
        return ""
    if part.get_content_type() == "text/html":
        return html_to_text(content)
    return content


def body_html(msg: EmailMessage) -> str | None:
    """The text/html part as-is, or None."""
    try:
        part = msg.get_body(preferencelist=("html",))
        if part is None:
            return None
        content = part.get_content()
    except Exception:  # noqa: BLE001
        return None
    return content if isinstance(content, str) else None


def attachments(msg: EmailMessage) -> list[dict[str, Any]]:
    """[{filename, content_type, size}] for every attachment part."""
    out: list[dict[str, Any]] = []
    try:
        parts = list(msg.iter_attachments())
    except Exception:  # noqa: BLE001
        return out
    for i, part in enumerate(parts, 1):
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            payload = None
        size = len(payload) if isinstance(payload, bytes) else 0
        out.append(
            {
                "filename": part.get_filename() or f"attachment-{i}",
                "content_type": part.get_content_type(),
                "size": size,
            }
        )
    return out


def attachment_parts(msg: EmailMessage) -> list[tuple[str, str, bytes]]:
    """(filename, content_type, bytes) for every attachment part with decodable content."""
    out: list[tuple[str, str, bytes]] = []
    try:
        parts = list(msg.iter_attachments())
    except Exception:  # noqa: BLE001
        return out
    for i, part in enumerate(parts, 1):
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001 — an undecodable part is skipped, the rest still land
            payload = None
        if isinstance(payload, bytes):
            out.append((part.get_filename() or f"attachment-{i}", part.get_content_type(), payload))
    return out


def summary(msg: EmailMessage) -> dict[str, Any]:
    """Header summary used by `inspect` and `mail threads`."""
    parts = sum(1 for _ in msg.walk()) if msg.is_multipart() else 1
    return {
        "from": addresses(msg, "From"),
        "to": addresses(msg, "To"),
        "cc": addresses(msg, "Cc"),
        "date": header_date(msg),
        "subject": str(msg.get("Subject") or "") or None,
        "message_id": _first_id(str(msg.get("Message-ID") or "")),
        "in_reply_to": _first_id(str(msg.get("In-Reply-To") or "")),
        "references": message_ids(str(msg.get("References") or "")),
        "parts": parts,
        "has_html": body_html(msg) is not None,
        "attachments": attachments(msg),
    }


def message_text(msg: EmailMessage) -> str:
    """The text `index`/`pack`/`search` see: key headers, a blank line, the body, attachments."""
    lines: list[str] = []
    for field in ("From", "To", "Cc", "Date", "Subject", "Message-ID"):
        value = header_date(msg) if field == "Date" else str(msg.get(field) or "")
        if value:
            lines.append(f"{field}: {value}")
    body = body_text(msg).strip()
    text = "\n".join(lines) + "\n\n" + body + ("\n" if body else "")
    atts = attachments(msg)
    if atts:
        text += (
            "\n"
            + "\n".join(
                f"attachment: {a['filename']} ({a['content_type']}, {a['size']} bytes)"
                for a in atts
            )
            + "\n"
        )
    return text


def eml_text(path: Path) -> str:
    return message_text(parse_eml(path))


def mbox_text(path: Path) -> str:
    """Every message as a `# <subject>` block, in mailbox order."""
    blocks = []
    for msg in iter_mbox(path):
        subject = str(msg.get("Subject") or "(no subject)")
        blocks.append(f"# {subject}\n{message_text(msg)}")
    return "\n".join(blocks) if blocks else ""


# ------------------------------------------------------------------- threads


def thread_groups(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group message summaries by Message-ID / In-Reply-To / References.

    Each input needs `message_id`, `in_reply_to`, `references`, `subject`,
    `date` and a `where` label (path, or `path#n` inside an mbox). Output:
    [{root_subject, first_date, messages: [{where, message_id, date, from,
    subject, depth}]}] sorted by first date; messages inside a thread are in
    date order; `depth` is the reply-chain length when the parent is present.
    """
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        while parent.get(i, i) != i:
            parent[i] = parent.get(parent[i], parent[i])
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_id: dict[str, int] = {}
    for i, m in enumerate(messages):
        parent.setdefault(i, i)
        if m.get("message_id"):
            by_id.setdefault(m["message_id"], i)
    for i, m in enumerate(messages):
        for ref in [m.get("in_reply_to"), *m.get("references", [])]:
            if ref and ref in by_id:
                union(i, by_id[ref])

    groups: dict[int, list[int]] = {}
    for i in range(len(messages)):
        groups.setdefault(find(i), []).append(i)

    def depth_of(i: int, seen: set[int]) -> int:
        m = messages[i]
        pid = m.get("in_reply_to")
        if pid and pid in by_id and by_id[pid] not in seen:
            seen.add(by_id[pid])
            return 1 + depth_of(by_id[pid], seen)
        return 1

    out: list[dict[str, Any]] = []
    for members in groups.values():
        ordered = sorted(members, key=lambda i: (messages[i].get("date") or "", i))
        root = messages[ordered[0]]
        out.append(
            {
                "root_subject": root.get("subject"),
                "first_date": root.get("date"),
                "messages": [
                    {
                        "where": messages[i]["where"],
                        "message_id": messages[i].get("message_id"),
                        "date": messages[i].get("date"),
                        "from": messages[i].get("from"),
                        "subject": messages[i].get("subject"),
                        "depth": depth_of(i, {i}),
                    }
                    for i in ordered
                ],
            }
        )
    out.sort(key=lambda g: (g["first_date"] or "", g["root_subject"] or ""))
    return out


# --------------------------------------------------------------------- names


def safe_filename(name: str, fallback: str = "attachment") -> str:
    """A file name safe on every platform: no separators, no control chars, no leading dots."""
    base = Path(name.replace("\\", "/")).name.strip()
    base = _UNSAFE.sub("_", base).strip("._")
    return base or fallback


def slug(text: str, max_len: int = 60) -> str:
    """Lower-case ASCII slug for file names built from subjects."""
    s = _SLUG_UNSAFE.sub("-", text.strip().lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:max_len].rstrip("-") or "message"
