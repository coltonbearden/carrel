#!/usr/bin/env python3
"""Generate carrel's committed test fixtures (spec: specs/14-fixtures.md).

Run from the repo root:  uv run python tests/fixtures/generate.py

Idempotent: re-running rewrites nothing unless content actually changed
(existing identical files are left untouched, so git stays clean).
Deterministic: fixed data, fixed dates, reportlab invariant mode; pandoc
outputs are pinned via SOURCE_DATE_EPOCH and the xlsx zip is re-stamped.
Dependencies: stdlib + Pillow + reportlab; the office fixtures (spec 18)
additionally need pandoc (docx/odt/epub/rtf) and openpyxl (xlsx) and are
skipped with a message when those are absent.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

FIXDIR = Path(__file__).resolve().parent

# Fixed instant for every embedded timestamp (2021-06-15 12:00:00 UTC).
FIXED_EPOCH = 1623758400
FIXED_TS = time.gmtime(FIXED_EPOCH)
FIXED_DT = datetime.fromtimestamp(FIXED_EPOCH, tz=UTC)
EXIF_DATETIME = "2021:06:15 12:00:00"

# Sentinels (referenced by tests; see specs/14-fixtures.md)
TXT_SENTINEL = "quixotic zephyr"
MD_SENTINEL = "melodious cartography"
PDF_SENTINEL = "palimpsest harbor"
OCR_TEXT = "CARREL OCR FIXTURE 42"
XLSX_SENTINEL = "vellum ledger"

# Office/ebook document metadata (docx core.xml, epub OPF); spec 18
OFFICE_TITLE = "Carrel Sample Document"
OFFICE_AUTHOR = "Fixture Generator"
OFFICE_DATE = "2021-06-15"

# sample.xlsx: 2 sheets, header row + 3 data rows, one numeric column each
XLSX_SHEETS: dict[str, list[list[object]]] = {
    "Books": [
        ["title", "shelf", "year"],
        ["Palimpsest Harbor", "A2", 1998],
        ["Zephyr Atlas", "B4", 2011],
        [XLSX_SENTINEL.title(), "C1", 2020],
    ],
    "Loans": [
        ["member", "title", "days_out"],
        ["Ada", "Zephyr Atlas", 14],
        ["Basil", "Palimpsest Harbor", 3],
        ["Clara", XLSX_SENTINEL.title(), 21],
    ],
}


# docx/odt/epub/rtf/xlsx come out of pandoc and openpyxl, whose bytes differ
# between tool versions (CI's pandoc is not the dev box's). They are committed
# once and kept; `--force` regenerates them deliberately. Everything else is
# pure-Python and must stay byte-identical, which CI checks.
FORCE = "--force" in sys.argv


def write_once(name: str, data: bytes) -> None:
    """Write a tool-generated fixture only when absent (or under --force)."""
    path = FIXDIR / name
    if path.exists() and not FORCE:
        print(f"  kept       {name}  (tool-generated; --force to regenerate)")
        return
    write(name, data)


def write(name: str, data: bytes) -> None:
    path = FIXDIR / name
    if path.exists() and path.read_bytes() == data:
        print(f"  unchanged  {name}")
        return
    path.write_bytes(data)
    print(f"  wrote      {name}  ({len(data)} bytes)")


# --------------------------------------------------------------------------
# text-ish fixtures
# --------------------------------------------------------------------------


def gen_txt() -> None:
    text = f"""\
Carrel sample text fixture. This paragraph exists so that plain-text
extraction, packing, and indexing have something honest to chew on. The
sentinel phrase for search tests is: {TXT_SENTINEL}.

Second paragraph. Redaction tests rely on the planted strings below,
which are synthetic and belong to nobody:

  contact email: jane.doe@example.com
  backup email:  j.public+desk@test.example.org
  ssn-style:     123-45-6789
  phone-style:   (555) 867-5309

Third paragraph, deliberately dull. A quiet desk, a stack of files, and
one {TXT_SENTINEL} drifting past the window for good measure.
"""
    write("sample.txt", text.encode())


def gen_md() -> None:
    text = f"""\
# Chapter One: The Reading Room

An opening paragraph about a small library desk. The markdown sentinel
phrase is *{MD_SENTINEL}*, planted here for extraction tests.

## Furniture

- a desk
- a lamp
- three drawers
- one squeaky chair

### Inventory notes

Some inline `code` and a fenced block:

```python
def shelve(book: str) -> str:
    return f"shelved: {{book}}"
```

# Chapter Two: The Catalogue

A second H1 chapter so chapter-splitting logic has a real boundary.
See the [desk project](https://example.com/reading-desk) link for tests
that care about links.

## Closing

Final paragraph mentioning {MD_SENTINEL} once more, then silence.
"""
    write("sample.md", text.encode())


def gen_html() -> None:
    text = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Carrel Sample Page</title>
  <style>body { font-family: serif; }</style>
</head>
<body>
  <h1>Carrel Sample Page</h1>
  <p>An HTML fixture with the usual furniture: headings, a table,
     an image reference, and a form.</p>

  <h2>Reading list</h2>
  <table>
    <tr><th>Title</th><th>Shelf</th><th>Status</th></tr>
    <tr><td>The Palimpsest</td><td>A2</td><td>out</td></tr>
    <tr><td>Zephyr Atlas</td><td>B4</td><td>in</td></tr>
    <tr><td>Cartography of Sound</td><td>C1</td><td>in</td></tr>
  </table>

  <h2>Cover art</h2>
  <p><img src="sample.png" alt="generated sample art" width="400" height="300"></p>

  <h2>Request a book</h2>
  <form action="/request" method="post">
    <label>Name: <input type="text" name="name"></label>
    <label>Title: <input type="text" name="title"></label>
    <label><input type="checkbox" name="agree"> I will return it</label>
    <button type="submit">Request</button>
  </form>
</body>
</html>
"""
    write("sample.html", text.encode())


RECORDS = [
    {"id": i, "name": name, "dept": dept, "score": score, "active": active}
    for i, (name, dept, score, active) in enumerate(
        [
            ("Ada", "archives", 91.5, True),
            ("Basil", "maps", 78.0, True),
            ("Clara", "archives", 88.25, False),
            ("Dmitri", "periodicals", 64.0, True),
            ("Edith", "maps", 95.75, True),
            ("Felix", "rare-books", 71.5, False),
            ("Greta", "periodicals", 83.0, True),
            ("Hugo", "rare-books", 59.5, False),
        ],
        start=1,
    )
]


def gen_json() -> None:
    sample = {
        "library": {
            "name": "reading desk test library",
            "location": {"city": "Exampleville", "floor": 3},
            "open": True,
        },
        "records": RECORDS[:4],
        "counts": {"books": 1204, "maps": 87, "overdue": 3},
    }
    write("sample.json", (json.dumps(sample, indent=2) + "\n").encode())
    write("records.json", (json.dumps(RECORDS, indent=2) + "\n").encode())


def gen_xml() -> None:
    shelves = []
    for shelf_id, books in [
        ("A", [("The Palimpsest", 1998), ("Harbor Lights", 2004)]),
        ("B", [("Zephyr Atlas", 2011), ("Quixotic Roads", 1987)]),
        ("C", [("Cartography of Sound", 2020)]),
    ]:
        rows = "\n".join(
            f'      <book year="{year}">\n'
            f"        <title>{title}</title>\n"
            f"        <status>in</status>\n"
            f"      </book>"
            for title, year in books
        )
        shelves.append(f'  <shelf id="{shelf_id}">\n{rows}\n  </shelf>')
    text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<library>\n" + "\n".join(shelves) + "\n</library>\n"
    )
    write("sample.xml", text.encode())


def gen_csv() -> None:
    header = "id,title,shelf,year,checked_out"
    titles = [
        "Palimpsest",
        "Zephyr",
        "Cartography",
        "Harbor",
        "Quixotic",
        "Melody",
        "Atlas",
        "Lantern",
        "Vellum",
        "Folio",
    ]
    rows = [header]
    for i in range(1, 21):
        title = f"{titles[(i - 1) % len(titles)]} Vol {1 + (i - 1) // len(titles)}"
        shelf = f"{'ABCD'[i % 4]}{i % 7 + 1}"
        year = 1980 + (i * 3) % 40
        out = "yes" if i % 3 == 0 else "no"
        rows.append(f"{i},{title},{shelf},{year},{out}")
    write("sample.csv", ("\n".join(rows) + "\n").encode())


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------


def make_art() -> Image.Image:
    """Deterministic 400x300 'art': gradient + shapes + text."""
    img = Image.new("RGB", (400, 300))
    px = img.load()
    for y in range(300):
        for x in range(400):
            px[x, y] = (30 + (x * 180) // 400, 40 + (y * 160) // 300, 110)
    d = ImageDraw.Draw(img)
    d.ellipse((240, 30, 370, 160), fill=(240, 200, 60), outline=(20, 20, 20), width=3)
    d.rectangle((30, 170, 180, 270), fill=(70, 160, 140), outline=(20, 20, 20), width=3)
    d.line((0, 290, 400, 150), fill=(230, 230, 230), width=4)
    font = ImageFont.load_default(size=26)
    d.text((30, 30), "desk sample art", font=font, fill=(255, 255, 255))
    return img


def png_bytes(img: Image.Image, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", **kw)
    return buf.getvalue()


def gen_images() -> Image.Image:
    art = make_art()
    write("sample.png", png_bytes(art))

    # sample.jpg — same art, JPEG, EXIF DateTimeOriginal via Pillow Image.Exif
    exif = Image.Exif()
    exif[0x010F] = (
        "deskfixture"  # Make (IFD0) — name-neutral: binaries are committed and never renamed
    )
    exif[0x0110] = "fixture-generator"  # Model (IFD0)
    exif.get_ifd(0x8769)[36867] = EXIF_DATETIME  # Exif IFD -> DateTimeOriginal
    buf = io.BytesIO()
    art.save(buf, "JPEG", quality=90, exif=exif)
    jpg = buf.getvalue()
    write("sample.jpg", jpg)
    write("sample-copy.jpg", jpg)  # byte-identical (dedupe fixture)

    # near-duplicate: 75% scale
    buf = io.BytesIO()
    art.resize((300, 225), Image.LANCZOS).save(buf, "JPEG", quality=90)
    write("sample-resized.jpg", buf.getvalue())

    # multi-size ICO from a square crop of the art
    square = art.crop((72, 22, 328, 278))  # 256x256
    buf = io.BytesIO()
    square.save(buf, "ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    write("sample.ico", buf.getvalue())
    return art


def make_scanned() -> Image.Image:
    """900x1200 white page with large black text — tesseract-friendly."""
    img = Image.new("RGB", (900, 1200), "white")
    d = ImageDraw.Draw(img)
    big = ImageFont.load_default(size=100)
    small = ImageFont.load_default(size=40)
    words = OCR_TEXT.split()  # CARREL / OCR / FIXTURE / 42
    d.text((100, 200), f"{words[0]} {words[1]}", font=big, fill="black")
    d.text((100, 380), f"{words[2]} {words[3]}", font=big, fill="black")
    d.text((100, 640), "Scanned page fixture for the", font=small, fill="black")
    d.text((100, 710), "the desk OCR pipeline tests.", font=small, fill="black")
    return img


def gen_scanned_png() -> Image.Image:
    img = make_scanned()
    write("scanned.png", png_bytes(img))
    return img


# --------------------------------------------------------------------------
# PDFs
# --------------------------------------------------------------------------


def gen_text_image_pdf(art: Image.Image) -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    _width, height = letter

    # page 1: text with sentinel + embedded PNG
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 90, "Carrel Text+Image Fixture")
    c.setFont("Helvetica", 12)
    lines = [
        "This is page one of the mixed-content PDF fixture.",
        f"The pdf sentinel phrase is: {PDF_SENTINEL}.",
        "Below, a PNG generated by the same fixture script is embedded",
        "so pdfimages/extract-images tests have something to pull out.",
    ]
    for i, line in enumerate(lines):
        c.drawString(72, height - 130 - 18 * i, line)
    c.drawImage(ImageReader(art), 72, height - 530, width=300, height=225)
    c.showPage()

    # page 2: more text
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 90, "Page Two: The Appendix")
    c.setFont("Helvetica", 12)
    for i, line in enumerate(
        [
            "Page two exists so page-count, split, and per-page text tests",
            "have a second page to point at. It repeats no sentinel; it just",
            "sits here being reliably, deterministically boring.",
        ]
    ):
        c.drawString(72, height - 130 - 18 * i, line)
    c.showPage()
    c.save()
    write("text+image.pdf", buf.getvalue())


def gen_form_pdf() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    _, height = letter
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 90, "Carrel AcroForm Fixture")
    c.setFont("Helvetica", 12)
    c.drawString(72, height - 132, "Name:")
    c.acroForm.textfield(
        name="name",
        x=130,
        y=height - 144,
        width=220,
        height=20,
        borderStyle="inset",
        forceBorder=True,
    )
    c.drawString(72, height - 180, "I agree:")
    c.acroForm.checkbox(name="agree", x=130, y=height - 188, size=16, forceBorder=True)
    c.showPage()
    c.save()
    write("form.pdf", buf.getvalue())


def gen_scanned_pdf(scanned: Image.Image) -> None:
    buf = io.BytesIO()
    scanned.save(buf, format="PDF", resolution=150, creationDate=FIXED_TS, modDate=FIXED_TS)
    write("scanned.pdf", buf.getvalue())


def gen_b_pdf() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    _, height = letter
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 90, "Fixture B")
    c.setFont("Helvetica", 12)
    for i, line in enumerate(
        [
            "A second, small PDF used as the other operand in merge and",
            "diff tests. Its distinguishing phrase is: second fiddle harbor.",
        ]
    ):
        c.drawString(72, height - 130 - 18 * i, line)
    c.showPage()
    c.save()
    write("b.pdf", buf.getvalue())


# --------------------------------------------------------------------------
# office & ebook documents (spec 18) — pandoc from sample.md; openpyxl for xlsx
# --------------------------------------------------------------------------


def _pandoc_bytes(pandoc: str, to_fmt: str, suffix: str, *extra: str) -> bytes:
    """Render sample.md with pandoc into `to_fmt`, deterministically (SOURCE_DATE_EPOCH)."""
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(FIXED_EPOCH)}
    with tempfile.TemporaryDirectory(prefix="carrel-fixtures-") as td:
        out = Path(td) / f"sample{suffix}"
        subprocess.run(
            [
                pandoc,
                "-f",
                "markdown",
                "-t",
                to_fmt,
                "-M",
                f"title={OFFICE_TITLE}",
                "-M",
                f"author={OFFICE_AUTHOR}",
                "-M",
                f"date={OFFICE_DATE}",
                *extra,
                str(FIXDIR / "sample.md"),
                "-o",
                str(out),
            ],
            check=True,
            env=env,
            capture_output=True,
        )
        return out.read_bytes()


def _all_present(*names: str) -> bool:
    return not FORCE and all((FIXDIR / n).exists() for n in names)


def gen_office_docs() -> None:
    names = ("sample.docx", "sample.odt", "sample.epub", "sample.rtf")
    if _all_present(*names):
        for n in names:
            print(f"  kept       {n}  (tool-generated; --force to regenerate)")
        return
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        print("skip: pandoc missing (sample.docx/.odt/.epub/.rtf not generated)")
        return
    write_once("sample.docx", _pandoc_bytes(pandoc, "docx", ".docx"))
    write_once("sample.odt", _pandoc_bytes(pandoc, "odt", ".odt"))
    write_once(
        "sample.epub",
        _pandoc_bytes(
            pandoc, "epub", ".epub", "-M", "lang=en", "-M", "identifier=urn:carrel:sample-epub"
        ),
    )
    write_once("sample.rtf", _pandoc_bytes(pandoc, "rtf", ".rtf", "-s"))


def _restamp_zip(data: bytes) -> bytes:
    """Rewrite a zip with fixed entry timestamps (openpyxl stamps them with now())."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            stamped = zipfile.ZipInfo(info.filename, date_time=FIXED_DT.timetuple()[:6])
            stamped.compress_type = info.compress_type
            stamped.external_attr = info.external_attr
            dst.writestr(stamped, src.read(info.filename))
    return out.getvalue()


def gen_xlsx() -> None:
    if _all_present("sample.xlsx"):
        print("  kept       sample.xlsx  (tool-generated; --force to regenerate)")
        return
    try:
        from openpyxl import Workbook
    except ImportError:
        print("skip: openpyxl missing (sample.xlsx not generated; uv sync --extra office)")
        return
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in XLSX_SHEETS.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    wb.properties.title = OFFICE_TITLE
    wb.properties.creator = OFFICE_AUTHOR
    wb.properties.created = FIXED_DT.replace(tzinfo=None)
    wb.properties.modified = FIXED_DT.replace(tzinfo=None)
    buf = io.BytesIO()
    wb.save(buf)
    write_once("sample.xlsx", _restamp_zip(buf.getvalue()))


# --------------------------------------------------------------------------


def main() -> None:
    print(f"generating fixtures in {FIXDIR}")
    gen_txt()
    gen_md()
    gen_html()
    gen_json()
    gen_xml()
    gen_csv()
    art = gen_images()
    scanned = gen_scanned_png()
    gen_text_image_pdf(art)
    gen_form_pdf()
    gen_scanned_pdf(scanned)
    gen_b_pdf()
    gen_office_docs()
    gen_xlsx()
    print("done.")


if __name__ == "__main__":
    main()
