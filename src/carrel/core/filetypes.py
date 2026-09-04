"""Detection of the supported file types (extension + magic-byte confirmation).

Bytes beat names: a `%PDF` header, PNG/JPEG/ICO signatures and an `{\\rtf`
prefix decide on their own. Zip containers (`PK\\x03\\x04`) are probed
read-only for their office/ebook flavour (epub, odt, docx, xlsx); an
unrecognised or broken zip falls back to the extension, never raises.
"""

from __future__ import annotations

import zipfile
from enum import StrEnum
from pathlib import Path

from carrel.core.output import CarrelInputError


class FileType(StrEnum):
    PDF = "pdf"
    MD = "md"
    JPG = "jpg"
    PNG = "png"
    ICO = "ico"
    TXT = "txt"
    HTML = "html"
    JSON = "json"
    XML = "xml"
    CSV = "csv"
    DOCX = "docx"
    ODT = "odt"
    EPUB = "epub"
    RTF = "rtf"
    XLSX = "xlsx"
    UNKNOWN = "unknown"

    @property
    def is_image(self) -> bool:
        return self in (FileType.JPG, FileType.PNG, FileType.ICO)

    @property
    def is_text(self) -> bool:
        return self in (
            FileType.MD,
            FileType.TXT,
            FileType.HTML,
            FileType.JSON,
            FileType.XML,
            FileType.CSV,
        )

    @property
    def is_document(self) -> bool:
        """Word-processor / ebook containers that pandoc reads (PDF keeps its own paths)."""
        return self in (FileType.DOCX, FileType.ODT, FileType.EPUB, FileType.RTF)


_EXT_MAP = {
    ".pdf": FileType.PDF,
    ".md": FileType.MD,
    ".markdown": FileType.MD,
    ".jpg": FileType.JPG,
    ".jpeg": FileType.JPG,
    ".png": FileType.PNG,
    ".ico": FileType.ICO,
    ".txt": FileType.TXT,
    ".text": FileType.TXT,
    ".html": FileType.HTML,
    ".htm": FileType.HTML,
    ".json": FileType.JSON,
    ".xml": FileType.XML,
    ".csv": FileType.CSV,
    ".docx": FileType.DOCX,
    ".odt": FileType.ODT,
    ".epub": FileType.EPUB,
    ".rtf": FileType.RTF,
    ".xlsx": FileType.XLSX,
    ".xlsm": FileType.XLSX,
}

_MAGIC = [
    (b"%PDF", FileType.PDF),
    (b"\x89PNG\r\n\x1a\n", FileType.PNG),
    (b"\xff\xd8\xff", FileType.JPG),
    (b"\x00\x00\x01\x00", FileType.ICO),
    (b"{\\rtf", FileType.RTF),
]

_ZIP_MAGIC = b"PK\x03\x04"
_ZIP_PROBE_ENTRIES = 64
_ZIP_MIMETYPES = {
    b"application/epub+zip": FileType.EPUB,
    b"application/vnd.oasis.opendocument.text": FileType.ODT,
}

SUPPORTED_EXTENSIONS = tuple(sorted(_EXT_MAP))


def _sniff_zip(path: Path) -> FileType | None:
    """Office/ebook flavour of a zip container; None for anything else or a broken zip."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()[:_ZIP_PROBE_ENTRIES]
            if "mimetype" in names:
                mimetype = zf.read("mimetype").strip()
                if mimetype in _ZIP_MIMETYPES:
                    return _ZIP_MIMETYPES[mimetype]
            if "[Content_Types].xml" in names:
                if any(n.startswith("word/") for n in names):
                    return FileType.DOCX
                if any(n.startswith("xl/") for n in names):
                    return FileType.XLSX
    except Exception:  # noqa: BLE001 — the probe must never raise (truncated/odd zips → by extension)
        return None
    return None


def sniff(path: Path) -> FileType | None:
    """Magic-byte detection for the binary types; None when inconclusive."""
    try:
        head = path.open("rb").read(16)
    except OSError:
        return None
    for magic, ftype in _MAGIC:
        if head.startswith(magic):
            return ftype
    if head.startswith(_ZIP_MAGIC):
        return _sniff_zip(path)
    return None


def detect(path: Path | str) -> FileType:
    path = Path(path)
    by_magic = sniff(path)
    by_ext = _EXT_MAP.get(path.suffix.lower())
    if by_magic is not None:
        return by_magic  # trust bytes over names
    return by_ext or FileType.UNKNOWN


def detect_or_die(path: Path | str) -> FileType:
    path = Path(path)
    if not path.exists():
        raise CarrelInputError(f"no such file: {path}")
    if not path.is_file():
        raise CarrelInputError(f"not a regular file: {path}")
    ftype = detect(path)
    if ftype is FileType.UNKNOWN:
        raise CarrelInputError(
            f"unsupported file type: {path.name} (supported: {', '.join(SUPPORTED_EXTENSIONS)})"
        )
    return ftype
