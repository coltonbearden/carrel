"""Detection of the 11 supported file types (extension + magic-byte confirmation)."""

from __future__ import annotations

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
}

_MAGIC = [
    (b"%PDF", FileType.PDF),
    (b"\x89PNG\r\n\x1a\n", FileType.PNG),
    (b"\xff\xd8\xff", FileType.JPG),
    (b"\x00\x00\x01\x00", FileType.ICO),
]

SUPPORTED_EXTENSIONS = tuple(sorted(_EXT_MAP))


def sniff(path: Path) -> FileType | None:
    """Magic-byte detection for the binary types; None when inconclusive."""
    try:
        head = path.open("rb").read(16)
    except OSError:
        return None
    for magic, ftype in _MAGIC:
        if head.startswith(magic):
            return ftype
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
