"""Email parsing shared by textextract, inspect, convert and `carrel mail`.

Everything is stdlib: `email` (RFC 5322 / MIME) for `.eml` and `mailbox` for
`.mbox`. Messages are parsed with `email.policy.default`, which gives header
objects with proper decoding (RFC 2047 subjects, address lists) and
`get_body()` / `iter_attachments()` for MIME trees.

Nothing here writes a message; `carrel mail` writes attachments and split
messages as plain files.
"""

from __future__ import annotations

import contextlib
import mailbox
import re
from collections.abc import Iterator
from datetime import UTC, datetime
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
    """RFC 5322 header block at the start: ≥2 well-known fields before the first blank line.

    `head` is a prefix of the file, so its final line may be cut in half — that
    line is ignored rather than judged (a header block of Received/DKIM/ARC
    lines easily runs past any fixed read).
    """
    lines = head.split(b"\n")
    if b"\n" in head and head[-1:] != b"\n":
        lines = lines[:-1]  # the read stopped mid-line
    seen = 0
    for line in lines:
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


def _unquote_mboxrd(raw: bytes) -> bytes:
    """Undo mboxrd/mboxo `>From ` escaping in a stored message body.

    Writers escape a body line starting with `From ` so it cannot be mistaken
    for the next envelope separator; readers must put it back or the text (and
    any signature over it) is wrong.
    """
    if b"\n>From " not in raw and not raw.startswith(b">From "):
        return raw
    return re.sub(rb"(?m)^>(>*From )", rb"\1", raw)


def iter_mbox_raw(path: Path) -> Iterator[bytes]:
    """The stored bytes of each message, in mailbox order (read-only, never locked).

    Raises CarrelInputError for an unreadable file or one with no `From `
    envelope line at all — `mailbox.mbox` reports such a file as empty, which
    would otherwise look like a mailbox of zero messages.
    """
    try:
        box = mailbox.mbox(str(path), factory=None, create=False)
    except (OSError, mailbox.Error) as e:
        raise CarrelInputError(f"cannot read mbox {path}: {e}") from e
    try:
        keys = list(box.iterkeys())
        if not keys and path.stat().st_size > 0:
            raise CarrelInputError(
                f"{path} has no mbox `From ` separator line — not a mailbox "
                "(a single message is an .eml)"
            )
        for key in keys:
            yield _unquote_mboxrd(box.get_bytes(key))
    finally:
        box.close()


def count_mbox(path: Path) -> int:
    """How many messages the mailbox holds, without parsing any of them."""
    try:
        box = mailbox.mbox(str(path), factory=None, create=False)
    except (OSError, mailbox.Error) as e:
        raise CarrelInputError(f"cannot read mbox {path}: {e}") from e
    try:
        return len(box.keys())
    finally:
        box.close()


def iter_mbox(path: Path) -> Iterator[EmailMessage]:
    """Messages of an mbox file in order (read-only; the file is never locked or rewritten)."""
    for raw in iter_mbox_raw(path):
        yield BytesParser(policy=policy.default).parsebytes(raw)


def header_datetime(msg: EmailMessage) -> datetime | None:
    """The Date header as an aware datetime, or None when absent or unusable.

    Reading the header is itself inside the guard: under `policy.default` the
    value is parsed lazily on access, and a nonsense year raises OverflowError
    there — one such message must not abort an index or pack run.
    """
    raw = header_str(msg, "Date")
    if not raw:
        return None
    try:
        when = parsedate_to_datetime(raw)
    except Exception:  # noqa: BLE001 — any malformed Date is "no date", never a crash
        return None
    if when.tzinfo is None:  # a `-0000` or malformed offset: treat as UTC
        return when.replace(tzinfo=UTC)
    return when


def header_date(msg: EmailMessage) -> str | None:
    """The Date header as ISO 8601 (timezone kept), or None when absent/unparseable."""
    when = header_datetime(msg)
    return when.isoformat(timespec="seconds") if when else None


def _instant(msg_summary: dict[str, Any]) -> datetime:
    """The message's instant for ordering; undated messages sort last."""
    raw = msg_summary.get("date")
    if not raw:
        return datetime.max.replace(tzinfo=UTC)
    try:
        when = datetime.fromisoformat(str(raw))
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def header_str(msg: Any, field: str) -> str:
    """A header as text, or "" when it is absent or refuses to render.

    Under `policy.default` a header is parsed when it is read, and a malformed
    one raises there — an address with an embedded newline raises ValueError on
    `str()`. Every read of a message header goes through here so one hostile
    message cannot abort an index, pack or thread run.
    """
    try:
        value = msg.get(field)
        return str(value) if value is not None else ""
    except Exception:  # noqa: BLE001 — an unrenderable header is "no header"
        return ""


def addresses(msg: EmailMessage, field: str) -> list[str]:
    """`Name <addr>` strings of an address header (empty when absent or unparseable).

    A header that decodes to something with a CR or LF in it makes
    `getaddresses` raise; a hostile-but-parseable message must not abort a
    whole index run, so the field degrades to empty.
    """
    try:
        values = [str(v) for v in (msg.get_all(field) or [])]
        pairs = getaddresses(values)
    except Exception:  # noqa: BLE001 — an unusable address header is "no addresses"
        return []
    out: list[str] = []
    for name, addr in pairs:
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
    content = _part_text(part)
    if content is None:
        return ""
    if part.get_content_type() == "text/html":
        return html_to_text(content)
    return content


def _part_text(part: Any) -> str | None:
    """A text part's content, falling back to a permissive decode.

    `get_content()` raises LookupError for a charset Python does not know —
    a mislabeled or typo'd `charset=` is routine in real mail, and dropping the
    body silently would index the message as headers only.
    """
    with contextlib.suppress(Exception):  # unknown charset: fall through to the raw payload
        content = part.get_content()
        if isinstance(content, str):
            return content
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, bytes):
        return None
    charset = part.get_content_charset() or ""
    for encoding in (charset, "utf-8", "cp1252"):
        if not encoding:
            continue
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def body_html(msg: EmailMessage) -> str | None:
    """The text/html part as-is, or None."""
    try:
        part = msg.get_body(preferencelist=("html",))
    except Exception:  # noqa: BLE001
        return None
    return _part_text(part) if part is not None else None


def _iter_attachment_parts(msg: Any) -> Iterator[Any]:
    """Every attachment part, descending into nested multiparts and forwarded messages.

    `EmailMessage.iter_attachments()` yields only the top level, so a
    "forward as attachment" (`message/rfc822`) or a nested `multipart/mixed`
    would otherwise be reported as one opaque part and its real attachments
    never seen.
    """
    try:
        parts = list(msg.iter_attachments())
    except Exception:  # noqa: BLE001 — a broken MIME tree has no attachments
        return
    for part in parts:
        content_type = part.get_content_type()
        if content_type == "message/rfc822" or part.get_content_maintype() == "multipart":
            inner = part.get_payload()
            inner_messages = inner if isinstance(inner, list) else [inner]
            for sub in inner_messages:
                if hasattr(sub, "iter_attachments"):
                    yield from _iter_attachment_parts(sub)
            continue
        yield part


def _attachment_name(part: Any, index: int) -> str:
    try:
        name = part.get_filename()
    except Exception:  # noqa: BLE001 — an undecodable filename header
        name = None
    return name or f"attachment-{index}"


def attachments(msg: EmailMessage) -> list[dict[str, Any]]:
    """[{filename, content_type, size}] for every attachment part, nested ones included."""
    out: list[dict[str, Any]] = []
    for i, part in enumerate(_iter_attachment_parts(msg), 1):
        out.append(
            {
                "filename": _attachment_name(part, i),
                "content_type": part.get_content_type(),
                "size": _encoded_size(part),
            }
        )
    return out


def _encoded_size(part: Any) -> int:
    """Decoded byte size, estimated from the encoded payload when that is cheaper.

    `inspect` and `index` only want a number, and base64-decoding every
    attachment on that path is wasted work; base64 is 3 bytes per 4 characters.
    """
    encoding = (part.get("Content-Transfer-Encoding") or "").strip().lower()
    raw = part.get_payload()
    if encoding == "base64" and isinstance(raw, str):
        chars = len(raw.replace("\n", "").replace("\r", "").rstrip("="))
        return chars * 3 // 4  # 4 base64 characters carry 3 bytes
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001
        return 0
    return len(payload) if isinstance(payload, bytes) else 0


def attachment_parts(msg: EmailMessage) -> list[tuple[str, str, bytes]]:
    """(filename, content_type, bytes) for every attachment with decodable content."""
    out: list[tuple[str, str, bytes]] = []
    for i, part in enumerate(_iter_attachment_parts(msg), 1):
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001 — an undecodable part is skipped, the rest still land
            payload = None
        if isinstance(payload, bytes):
            out.append((_attachment_name(part, i), part.get_content_type(), payload))
    return out


def summary(msg: EmailMessage) -> dict[str, Any]:
    """Header summary used by `inspect` and `mail threads`."""
    parts = sum(1 for _ in msg.walk()) if msg.is_multipart() else 1
    return {
        "from": addresses(msg, "From"),
        "to": addresses(msg, "To"),
        "cc": addresses(msg, "Cc"),
        "date": header_date(msg),
        "subject": header_str(msg, "Subject") or None,
        "message_id": _first_id(header_str(msg, "Message-ID")),
        "in_reply_to": _first_id(header_str(msg, "In-Reply-To")),
        "references": message_ids(header_str(msg, "References")),
        "parts": parts,
        "has_html": body_html(msg) is not None,
        "attachments": attachments(msg),
    }


def message_text(msg: EmailMessage) -> str:
    """The text `index`/`pack`/`search` see: key headers, a blank line, the body, attachments."""
    lines: list[str] = []
    for field in ("From", "To", "Cc", "Date", "Subject", "Message-ID"):
        value = header_date(msg) if field == "Date" else header_str(msg, field)
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
    subject, depth}]}] sorted by first instant; messages inside a thread are in
    date order; `depth` is the reply-chain length when the parent is present.

    Ordering compares parsed instants, not ISO text: correspondents in two
    timezones would otherwise sort by wall clock. Copies of one message (the
    same Message-ID in a mailbox and in its split-out `.eml`) join the same
    thread rather than fracturing it, and a reply chain of any length is walked
    iteratively — a mailing-list megathread must not hit the recursion limit.
    """
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        root = i
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(i, i) != i:  # path compression, iteratively
            parent[i], i = root, parent[i]
        return root

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
        if m.get("message_id") and by_id[m["message_id"]] != i:
            union(by_id[m["message_id"]], i)  # the same message twice: one thread, not two
        for ref in [m.get("in_reply_to"), *m.get("references", [])]:
            if ref and ref in by_id:
                union(i, by_id[ref])

    groups: dict[int, list[int]] = {}
    for i in range(len(messages)):
        groups.setdefault(find(i), []).append(i)

    def depth_of(start: int) -> int:
        """Length of the reply chain above `start`, walked iteratively."""
        depth = 1
        seen = {start}
        current = start
        while True:
            pid = messages[current].get("in_reply_to")
            if not pid or pid not in by_id:
                return depth
            nxt = by_id[pid]
            if nxt in seen:
                return depth
            seen.add(nxt)
            current = nxt
            depth += 1

    out: list[dict[str, Any]] = []
    for members in groups.values():
        ordered = sorted(members, key=lambda i: (_instant(messages[i]), i))
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
                        "depth": depth_of(i),
                    }
                    for i in ordered
                ],
            }
        )
    out.sort(key=lambda g: (_instant(g["messages"][0]), g["root_subject"] or ""))
    return out


# --------------------------------------------------------------------- names


# Names cmd.exe resolves to devices rather than files, whatever the extension.
_WINDOWS_DEVICES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{n}" for n in range(1, 10)),
        *(f"lpt{n}" for n in range(1, 10)),
    }
)
MAX_FILENAME = 100  # bytes of stem kept; ext.4 filesystems cap a name at 255


def safe_filename(name: str, fallback: str = "attachment", *, max_len: int = MAX_FILENAME) -> str:
    """A file name safe on every platform.

    No separators, no control characters, no leading dots, no Windows device
    name, and short enough that the filesystem accepts it — an attachment name
    can legitimately run to hundreds of characters (RFC 2231 continuations),
    and `File name too long` from deep inside a write is not a useful error.
    """
    base = Path(name.replace("\\", "/")).name.strip()
    base = _UNSAFE.sub("_", base).strip("._")
    if not base:
        return fallback
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    suffix = suffix[:20]
    keep = max(1, max_len - (len(suffix) + 1 if suffix else 0))
    stem = stem[:keep].rstrip("._-") or fallback
    if stem.lower() in _WINDOWS_DEVICES:  # after the trim, or it would strip the guard back off
        stem = f"{stem}_"
    return f"{stem}.{suffix}" if suffix else stem


def slug(text: str, max_len: int = 60) -> str:
    """Lower-case ASCII slug for file names built from subjects."""
    s = _SLUG_UNSAFE.sub("-", text.strip().lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:max_len].rstrip("-") or "message"
