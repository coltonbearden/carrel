"""Detection of the supported file types (extension + magic-byte confirmation).

Bytes beat names: a `%PDF` header, PNG/JPEG/ICO signatures and an `{\\rtf`
prefix decide on their own. Zip containers (`PK\\x03\\x04`) are probed
read-only for their office/ebook flavour (epub, odt, docx, xlsx); an
unrecognised or broken zip falls back to the extension, never raises.

Source files (`.py`, `.rs`, `.toml`, ...) are typed `CODE` from their extension
alone -- they carry no signature. `SOURCE_EXTENSIONS` maps each to a language
label for syntax fences; the label is presentation only and is never stored in
the desk database, which holds the `FileType` value (D-010).

Email (`.eml`, `.mbox`) is text with a recognisable shape rather than a magic
number, so its sniff applies only to files whose extension is not mapped
(D-012): a `.txt` that starts with `From:` stays TXT, while an extension-less
export that carries an RFC 5322 header block is EML.
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
    CODE = "code"
    EML = "eml"
    MBOX = "mbox"
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

    @property
    def is_code(self) -> bool:
        """Plain-text source files, read verbatim (no extractor, no binary)."""
        return self is FileType.CODE

    @property
    def is_mail(self) -> bool:
        """Email: one RFC 5322 message (eml) or a mailbox of them (mbox)."""
        return self in (FileType.EML, FileType.MBOX)


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
    ".eml": FileType.EML,
    ".mbox": FileType.MBOX,
    ".mbx": FileType.MBOX,
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

# Plain-text source and config files: extension -> language label for syntax
# fences. Deliberately separate from _EXT_MAP so detect_or_die's "supported:"
# message stays the list of types with real extractors, and so a .json/.xml/
# .csv/.md file keeps its richer FileType instead of collapsing to CODE.
SOURCE_EXTENSIONS = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".vue": "vue",
    ".svelte": "svelte",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".rb": "ruby",
    ".php": "php",
    ".pl": "perl",
    ".pm": "perl",
    ".lua": "lua",
    ".r": "r",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".ml": "ocaml",
    ".fs": "fsharp",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".properties": "ini",
    ".mk": "makefile",
    ".cmake": "cmake",
    ".gradle": "gradle",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".rst": "rst",
    ".adoc": "asciidoc",
    ".tex": "latex",
}

# Build files that carry their meaning in the name, not an extension.
SOURCE_FILENAMES = {
    "makefile": "makefile",
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "rakefile": "ruby",
    "gemfile": "ruby",
    "brewfile": "ruby",
    "vagrantfile": "ruby",
    "justfile": "just",
    "procfile": "procfile",
}


def source_language(path: Path | str) -> str | None:
    """Language label for a source file, or None when it is not one."""
    path = Path(path)
    return SOURCE_EXTENSIONS.get(path.suffix.lower()) or SOURCE_FILENAMES.get(path.name.lower())


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


def _sniff_mail(path: Path) -> FileType | None:
    """eml / mbox by shape — only consulted for unmapped extensions (D-012)."""
    from carrel.core.mail import looks_like_eml, looks_like_mbox

    try:
        head = path.open("rb").read(2048)
    except OSError:
        return None
    if looks_like_mbox(head):
        return FileType.MBOX
    if looks_like_eml(head):
        return FileType.EML
    return None


def detect(path: Path | str) -> FileType:
    path = Path(path)
    by_magic = sniff(path)
    by_ext = _EXT_MAP.get(path.suffix.lower())
    if by_magic is not None:
        return by_magic  # trust bytes over names
    if by_ext is not None:
        return by_ext
    if source_language(path):
        return FileType.CODE
    return _sniff_mail(path) or FileType.UNKNOWN


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
