"""Tests for `carrel edit` (pdf/image/text/json).

Wave-1 constraint: no conftest helpers, no tests/fixtures/ — every input is
synthesized here (pypdf blank pages, Pillow images, tmp_path text/json).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image
from pypdf import PdfReader, PdfWriter

from carrel.cli import cli
from conftest import needs

# ------------------------------------------------------------------ helpers


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str) -> dict:
    result = run("--json", *args)
    return json.loads(result.output)


def make_pdf(path: Path, pages: int, *, password: str | None = None) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    if password:
        writer.encrypt(password)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def make_image(path: Path, size=(40, 20), *, exif_make: str | None = None,
               color=(200, 30, 30)) -> Path:
    img = Image.new("RGB", size, color)
    kwargs = {}
    if exif_make is not None:
        exif = Image.Exif()
        exif[271] = exif_make  # 271 = Make
        kwargs["exif"] = exif
    img.save(path, **kwargs)
    return path


# ------------------------------------------------------------------ edit pdf


def test_pdf_merge_page_count_is_sum(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", 2)
    b = make_pdf(tmp_path / "b.pdf", 3)
    out = tmp_path / "merged.pdf"
    record = run_json("edit", "pdf", str(a), "--merge", str(b), "-o", str(out))
    assert record["pages_in"] == 5 and record["pages_out"] == 5
    assert len(PdfReader(out).pages) == 5


def test_pdf_split_writes_one_file_per_page(tmp_path: Path):
    src = make_pdf(tmp_path / "tri.pdf", 3)
    out_dir = tmp_path / "parts"
    record = run_json("edit", "pdf", str(src), "--split", "-o", str(out_dir))
    files = sorted(out_dir.glob("*.pdf"))
    assert len(files) == 3
    assert all(len(PdfReader(f).pages) == 1 for f in files)
    assert isinstance(record["output"], list) and len(record["output"]) == 3


def test_pdf_pages_extracts_range(tmp_path: Path):
    src = make_pdf(tmp_path / "five.pdf", 5)
    out = tmp_path / "some.pdf"
    record = run_json("edit", "pdf", str(src), "--pages", "1-2,5", "-o", str(out))
    assert record["pages_out"] == 3
    assert len(PdfReader(out).pages) == 3


def test_pdf_pages_out_of_range_is_bad_input(tmp_path: Path):
    src = make_pdf(tmp_path / "two.pdf", 2)
    run("edit", "pdf", str(src), "--pages", "9", "-o", str(tmp_path / "x.pdf"), expect=4)


def test_pdf_rotate_sets_rotation(tmp_path: Path):
    src = make_pdf(tmp_path / "r.pdf", 2)
    out = tmp_path / "rot.pdf"
    run_json("edit", "pdf", str(src), "--rotate", "90", "-o", str(out))
    reader = PdfReader(out)
    assert all(page.rotation == 90 for page in reader.pages)


def test_pdf_rotate_must_be_multiple_of_90(tmp_path: Path):
    src = make_pdf(tmp_path / "r.pdf", 1)
    run("edit", "pdf", str(src), "--rotate", "45", "-o", str(tmp_path / "x.pdf"), expect=2)


def test_pdf_no_operation_is_usage_error(tmp_path: Path):
    src = make_pdf(tmp_path / "n.pdf", 1)
    run("edit", "pdf", str(src), expect=2)


def test_pdf_wrong_type_exits_4(tmp_path: Path):
    img = make_image(tmp_path / "pic.png")
    run("edit", "pdf", str(img), "--rotate", "90", expect=4)


def test_pdf_missing_file_exits_4(tmp_path: Path):
    run("edit", "pdf", str(tmp_path / "ghost.pdf"), "--rotate", "90", expect=4)


def test_pdf_overwrite_needs_force(tmp_path: Path):
    src = make_pdf(tmp_path / "s.pdf", 1)
    out = make_pdf(tmp_path / "existing.pdf", 1)
    run("edit", "pdf", str(src), "--rotate", "90", "-o", str(out), expect=1)
    record = run_json("edit", "pdf", str(src), "--rotate", "90", "-o", str(out), "--force")
    assert record["output"] == str(out)


def test_pdf_default_output_name(tmp_path: Path):
    src = make_pdf(tmp_path / "doc.pdf", 2)
    record = run_json("edit", "pdf", str(src), "--pages", "1")
    assert record["output"] == str(tmp_path / "doc.edited.pdf")
    assert (tmp_path / "doc.edited.pdf").exists()


@needs("qpdf")
def test_pdf_decrypt_with_qpdf(tmp_path: Path):
    src = make_pdf(tmp_path / "locked.pdf", 2, password="hunter2")
    assert PdfReader(src).is_encrypted
    out = tmp_path / "open.pdf"
    record = run_json("edit", "pdf", str(src), "--decrypt", "hunter2", "-o", str(out))
    assert "decrypt" in record["operations"]
    reader = PdfReader(out)
    assert not reader.is_encrypted and len(reader.pages) == 2


@needs("qpdf")
def test_pdf_linearize_with_qpdf(tmp_path: Path):
    from carrel.core import adapters

    src = make_pdf(tmp_path / "lin.pdf", 2)
    out = tmp_path / "lin-out.pdf"
    run_json("edit", "pdf", str(src), "--linearize", "-o", str(out))
    proc = adapters.run("qpdf", "--check-linearization", str(out))
    assert proc.returncode == 0, proc.stderr


def test_pdf_encrypted_without_decrypt_exits_4(tmp_path: Path):
    src = make_pdf(tmp_path / "locked.pdf", 1, password="pw")
    run("edit", "pdf", str(src), "--rotate", "90", "-o", str(tmp_path / "x.pdf"), expect=4)


def test_pdf_qpdf_missing_degrades_to_exit_3(tmp_path: Path, monkeypatch):
    from carrel.core import adapters as ad

    broken = ad.Adapter("qpdf", ("definitely-not-a-real-binary-xyz",),
                        ("--version",), ad.ADAPTERS["qpdf"].install_hint,
                        ad.ADAPTERS["qpdf"].purpose)
    monkeypatch.setitem(ad.ADAPTERS, "qpdf", broken)
    src = make_pdf(tmp_path / "s.pdf", 1)
    result = CliRunner().invoke(
        cli, ["edit", "pdf", str(src), "--linearize", "-o", str(tmp_path / "o.pdf")])
    assert result.exit_code == 3
    assert "qpdf" in result.stderr and "install" in result.stderr


# ---------------------------------------------------------------- edit image


def test_image_rotate_90_swaps_dimensions(tmp_path: Path):
    src = make_image(tmp_path / "w.png", size=(40, 20))
    out = tmp_path / "r.png"
    record = run_json("edit", "image", str(src), "--rotate", "90", "-o", str(out))
    assert record["size_in"] == [40, 20] and record["size_out"] == [20, 40]
    with Image.open(out) as img:
        assert img.size == (20, 40)


def test_image_resize_exact_and_percent(tmp_path: Path):
    src = make_image(tmp_path / "s.png", size=(40, 20))
    record = run_json("edit", "image", str(src), "--resize", "10x5",
                      "-o", str(tmp_path / "a.png"))
    assert record["size_out"] == [10, 5]
    record = run_json("edit", "image", str(src), "--resize", "50%",
                      "-o", str(tmp_path / "b.png"))
    assert record["size_out"] == [20, 10]


def test_image_crop(tmp_path: Path):
    src = make_image(tmp_path / "c.png", size=(40, 20))
    record = run_json("edit", "image", str(src), "--crop", "5,5,10,8",
                      "-o", str(tmp_path / "out.png"))
    assert record["size_out"] == [10, 8]


def test_image_strip_removes_exif(tmp_path: Path):
    src = make_image(tmp_path / "meta.jpg", exif_make="carrel-test")
    with Image.open(src) as img:
        assert img.getexif().get(271) == "carrel-test"
    out = tmp_path / "clean.jpg"
    record = run_json("edit", "image", str(src), "--strip", "-o", str(out))
    assert record["stripped"] is True
    with Image.open(out) as img:
        assert 271 not in img.getexif()


def test_image_exif_preserved_without_strip(tmp_path: Path):
    src = make_image(tmp_path / "meta.jpg", exif_make="carrel-test")
    out = tmp_path / "kept.jpg"
    run_json("edit", "image", str(src), "--resize", "50%", "-o", str(out))
    with Image.open(out) as img:
        assert img.getexif().get(271) == "carrel-test"


def test_image_quality_shrinks_jpeg(tmp_path: Path):
    import random

    rng = random.Random(42)
    noisy = Image.new("RGB", (64, 64))
    noisy.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                   for _ in range(64 * 64)])
    src = tmp_path / "noise.jpg"
    noisy.save(src, quality=95)
    lo, hi = tmp_path / "lo.jpg", tmp_path / "hi.jpg"
    run_json("edit", "image", str(src), "--quality", "10", "-o", str(lo))
    run_json("edit", "image", str(src), "--quality", "95", "-o", str(hi))
    assert lo.stat().st_size < hi.stat().st_size


def test_image_wrong_type_exits_4(tmp_path: Path):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    run("edit", "image", str(pdf), "--rotate", "90", expect=4)


def test_image_overwrite_needs_force(tmp_path: Path):
    src = make_image(tmp_path / "a.png")
    out = make_image(tmp_path / "b.png")
    run("edit", "image", str(src), "--rotate", "90", "-o", str(out), expect=1)
    run_json("edit", "image", str(src), "--rotate", "90", "-o", str(out), "--force")


def test_image_no_operation_is_usage_error(tmp_path: Path):
    src = make_image(tmp_path / "a.png")
    run("edit", "image", str(src), expect=2)


# ----------------------------------------------------------------- edit text


def test_text_literal_replace(tmp_path: Path):
    src = tmp_path / "note.txt"
    src.write_text("apples and apples, not oranges\n")
    out = tmp_path / "out.txt"
    record = run_json("edit", "text", str(src), "--find", "apples",
                      "--replace", "pears", "-o", str(out))
    assert record["replacements"] == 2
    assert out.read_text() == "pears and pears, not oranges\n"


def test_text_regex_replace(tmp_path: Path):
    src = tmp_path / "doc.md"
    src.write_text("v1.2 then v3.4 done\n")
    out = tmp_path / "out.md"
    record = run_json("edit", "text", str(src), "--find", r"v(\d)\.(\d)",
                      "--replace", r"version \1-\2", "--regex", "-o", str(out))
    assert record["replacements"] == 2
    assert out.read_text() == "version 1-2 then version 3-4 done\n"


def test_text_in_place_requires_flag(tmp_path: Path):
    src = tmp_path / "a.txt"
    src.write_text("hello world\n")
    # neither -o nor -i → usage error, file untouched
    run("edit", "text", str(src), "--find", "hello", "--replace", "bye", expect=2)
    assert src.read_text() == "hello world\n"
    record = run_json("edit", "text", str(src), "--find", "hello", "--replace", "bye", "-i")
    assert record["in_place"] is True
    assert src.read_text() == "bye world\n"


def test_text_output_overwrite_needs_force(tmp_path: Path):
    src = tmp_path / "a.txt"
    src.write_text("x")
    existing = tmp_path / "b.txt"
    existing.write_text("keep me")
    run("edit", "text", str(src), "--find", "x", "--replace", "y",
        "-o", str(existing), expect=1)
    assert existing.read_text() == "keep me"
    run_json("edit", "text", str(src), "--find", "x", "--replace", "y",
             "-o", str(existing), "--force")
    assert existing.read_text() == "y"


def test_text_both_i_and_o_is_usage_error(tmp_path: Path):
    src = tmp_path / "a.txt"
    src.write_text("x")
    run("edit", "text", str(src), "--find", "x", "--replace", "y",
        "-i", "-o", str(tmp_path / "o.txt"), expect=2)


def test_text_wrong_type_exits_4(tmp_path: Path):
    pdf = make_pdf(tmp_path / "d.pdf", 1)
    run("edit", "text", str(pdf), "--find", "a", "--replace", "b", "-i", expect=4)


def test_text_bad_regex_is_usage_error(tmp_path: Path):
    src = tmp_path / "a.txt"
    src.write_text("x")
    run("edit", "text", str(src), "--find", "(", "--replace", "y", "--regex", "-i", expect=2)


# ----------------------------------------------------------------- edit json


def test_json_set_and_del_roundtrip(tmp_path: Path):
    src = tmp_path / "cfg.json"
    src.write_text(json.dumps({"a": {"b": {"c": 1}}, "drop": True, "keep": "yes"}))
    out = tmp_path / "out.json"
    record = run_json("edit", "json", str(src), "--set", "a.b.c=42",
                      "--del", "drop", "-o", str(out))
    data = json.loads(out.read_text())
    assert data == {"a": {"b": {"c": 42}}, "keep": "yes"}
    assert record["set"] == [{"path": "a.b.c", "value": 42}]
    assert record["deleted"] == ["drop"]


def test_json_value_parsing_and_string_fallback(tmp_path: Path):
    src = tmp_path / "v.json"
    src.write_text("{}")
    out = tmp_path / "out.json"
    run_json("edit", "json", str(src),
             "--set", "num=3.5", "--set", "flag=true", "--set", "obj={\"x\": 1}",
             "--set", "name=plain words", "--set", "nested.deep=ok",
             "-o", str(out))
    data = json.loads(out.read_text())
    assert data["num"] == 3.5
    assert data["flag"] is True
    assert data["obj"] == {"x": 1}
    assert data["name"] == "plain words"  # not valid JSON → string fallback
    assert data["nested"] == {"deep": "ok"}


def test_json_list_index_paths(tmp_path: Path):
    src = tmp_path / "l.json"
    src.write_text(json.dumps({"items": [{"id": 1}, {"id": 2}]}))
    out = tmp_path / "out.json"
    run_json("edit", "json", str(src), "--set", "items.1.id=99",
             "--del", "items.0", "-o", str(out))
    assert json.loads(out.read_text()) == {"items": [{"id": 99}]}


def test_json_del_missing_key_fails(tmp_path: Path):
    src = tmp_path / "m.json"
    src.write_text("{}")
    run("edit", "json", str(src), "--del", "nope", "-o", str(tmp_path / "o.json"), expect=1)


def test_json_invalid_source_exits_4(tmp_path: Path):
    src = tmp_path / "bad.json"
    src.write_text("{not json!")
    run("edit", "json", str(src), "--set", "a=1", "-o", str(tmp_path / "o.json"), expect=4)


def test_json_wrong_type_exits_4(tmp_path: Path):
    src = tmp_path / "a.txt"
    src.write_text("hello")
    run("edit", "json", str(src), "--set", "a=1", expect=4)


def test_json_no_operation_is_usage_error(tmp_path: Path):
    src = tmp_path / "a.json"
    src.write_text("{}")
    run("edit", "json", str(src), expect=2)


def test_json_overwrite_src_needs_force(tmp_path: Path):
    src = tmp_path / "a.json"
    src.write_text("{}")
    run("edit", "json", str(src), "--set", "a=1", "-o", str(src), expect=1)
    run_json("edit", "json", str(src), "--set", "a=1", "-o", str(src), "--force")
    assert json.loads(src.read_text()) == {"a": 1}


# ------------------------------------------------------------------- plumbing


def test_edit_help_and_subcommand_help():
    result = run("edit", "--help")
    for name in ("pdf", "image", "text", "json"):
        assert name in result.output
        run("edit", name, "--help")


def test_json_flag_emits_single_json_object(tmp_path: Path):
    src = tmp_path / "j.json"
    src.write_text("{}")
    result = run("--json", "edit", "json", str(src), "--set", "a=1",
                 "-o", str(tmp_path / "o.json"))
    record = json.loads(result.output)  # would raise if anything but one JSON doc
    assert record["action"] == "edit-json"
