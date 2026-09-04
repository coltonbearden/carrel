---
description: OCR an image or PDF into text (txt/md) or a searchable PDF using the carrel CLI
argument-hint: <image-or-pdf> [to txt|md|searchable pdf] [language]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

OCR the file the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real flags of `carrel ocr` (verify with `carrel ocr --help` if unsure — never invent flags):

```
carrel ocr SRC [-o OUT] [--lang LANG] [--to txt|pdf|md] [--redo] [--force]
```

- `SRC`: a jpg/png image (runs through tesseract) or a PDF (runs through ocrmypdf; born-digital pages pass through untouched).
- `--to txt|pdf|md` (default txt): extracted text, or a searchable PDF layer.
- `-o/--out PATH`: output file; default is SRC with the target extension (`SRC.ocr.pdf` for pdf → pdf).
- `--lang LANG` (default eng): tesseract language codes, e.g. `eng` or `eng+deu` — set this when the user mentions a non-English document.
- `--redo`: re-OCR PDF pages even if they already have text (only when the user says the existing text layer is bad).
- `--force`: only when the user explicitly wants an existing output overwritten.

Afterwards, tell the user where the output landed. For `--to txt/md`, offer to show or summarize the extracted text. Exit code 3 means tesseract/ocrmypdf is missing — relay the install hint from stderr (`sudo apt install tesseract-ocr` / `ocrmypdf`). Exit code 4 means the input type isn't OCR-able.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
