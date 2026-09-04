"""Tests for `carrel diff` (spec 03)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs
from PIL import Image, ImageDraw

from carrel.cli import cli
from carrel.commands.diff import diff_files
from carrel.core.output import CarrelInputError


def run(*args: str):
    return CliRunner().invoke(cli, list(args))


def diff_json(*args: str) -> tuple[int, dict]:
    res = run("diff", *args, "--json")
    assert res.exit_code in (0, 1), res.output
    return res.exit_code, json.loads(res.output)


# ----------------------------------------------------------------- text mode


def test_identical_file_exit_0(fixtures: Path):
    code, obj = diff_json(str(fixtures / "sample.txt"), str(fixtures / "sample.txt"))
    assert code == 0
    assert obj["identical"] is True
    assert obj["mode"] == "text"
    assert obj["diff"] == ""


def test_modified_text_exit_1(fixtures: Path, tmp_path: Path):
    modified = tmp_path / "sample.txt"
    modified.write_text(
        (fixtures / "sample.txt").read_text().replace("quixotic zephyr", "boring breeze")
    )
    code, obj = diff_json(str(fixtures / "sample.txt"), str(modified))
    assert code == 1
    assert obj["identical"] is False
    assert obj["added"] >= 1 and obj["removed"] >= 1
    assert "-" in obj["diff"] and "+" in obj["diff"]
    assert "boring breeze" in obj["diff"]


def test_text_fallback_on_textish_mismatch(fixtures: Path):
    code, obj = diff_json(str(fixtures / "sample.txt"), str(fixtures / "sample.md"))
    assert code == 1
    assert obj["mode"] == "text"


def test_forced_text_mode_on_json_pair(fixtures: Path):
    code, obj = diff_json(
        str(fixtures / "sample.json"), str(fixtures / "records.json"), "--mode", "text"
    )
    assert obj["mode"] == "text"
    assert code == 1


def test_human_output_colorless_capture(fixtures: Path, tmp_path: Path):
    modified = tmp_path / "sample.txt"
    modified.write_text((fixtures / "sample.txt").read_text() + "tail line\n")
    res = run("diff", str(fixtures / "sample.txt"), str(modified))
    assert res.exit_code == 1
    assert "+tail line" in res.output
    same = run("diff", str(fixtures / "sample.txt"), str(fixtures / "sample.txt"))
    assert same.exit_code == 0
    assert "identical" in same.output


# --------------------------------------------------------------- struct: json


def test_json_changed_dotted_path(fixtures: Path, tmp_path: Path):
    data = json.loads((fixtures / "sample.json").read_text())
    data["records"][0]["score"] = 99.9
    modified = tmp_path / "sample.json"
    modified.write_text(json.dumps(data, indent=2))
    code, obj = diff_json(str(fixtures / "sample.json"), str(modified))
    assert code == 1
    assert obj["mode"] == "struct"
    changed = {c["path"]: c for c in obj["changed"]}
    assert "records.0.score" in changed
    assert changed["records.0.score"]["a"] == 91.5
    assert changed["records.0.score"]["b"] == 99.9


def test_json_added_and_removed_paths(fixtures: Path, tmp_path: Path):
    data = json.loads((fixtures / "sample.json").read_text())
    data["annex"] = {"wing": "east"}
    del data["counts"]["maps"]
    modified = tmp_path / "sample.json"
    modified.write_text(json.dumps(data))
    code, obj = diff_json(str(fixtures / "sample.json"), str(modified))
    assert code == 1
    assert "annex.wing" in obj["added"]
    assert "counts.maps" in obj["removed"]


def test_json_identical_struct(fixtures: Path, tmp_copy):
    copy = tmp_copy("sample.json")
    code, obj = diff_json(str(fixtures / "sample.json"), str(copy))
    assert code == 0
    assert obj["identical"] is True and obj["mode"] == "struct"


def test_invalid_json_exit_4(fixtures: Path, tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    res = run("diff", str(fixtures / "sample.json"), str(bad))
    assert res.exit_code == 4


# ---------------------------------------------------------------- struct: csv


def test_csv_cell_change_row_and_column(fixtures: Path, tmp_path: Path):
    lines = (fixtures / "sample.csv").read_text().splitlines()
    parts = lines[2].split(",")  # data row 2
    parts[1] = "Renamed Volume"  # title column
    lines[2] = ",".join(parts)
    modified = tmp_path / "sample.csv"
    modified.write_text("\n".join(lines) + "\n")
    code, obj = diff_json(str(fixtures / "sample.csv"), str(modified))
    assert code == 1
    assert obj["mode"] == "struct"
    assert {"row": 2, "column": "title", "a": "Zephyr Vol 1", "b": "Renamed Volume"} in obj[
        "changed"
    ]
    assert obj["rows_added"] == [] and obj["rows_removed"] == []


def test_csv_row_added(fixtures: Path, tmp_path: Path):
    text = (fixtures / "sample.csv").read_text()
    modified = tmp_path / "sample.csv"
    modified.write_text(text + "21,New Book,A1,2024,no\n")
    code, obj = diff_json(str(fixtures / "sample.csv"), str(modified))
    assert code == 1
    assert obj["rows_a"] == 20 and obj["rows_b"] == 21
    assert obj["rows_added"] == [21]
    assert obj["changed"] == []


# ---------------------------------------------------------------- struct: xml


def test_xml_changed_element_path(fixtures: Path, tmp_path: Path):
    modified = tmp_path / "sample.xml"
    modified.write_text(
        (fixtures / "sample.xml").read_text().replace("Harbor Lights", "Harbor Nights")
    )
    code, obj = diff_json(str(fixtures / "sample.xml"), str(modified))
    assert code == 1
    assert obj["mode"] == "struct"
    changed = {c["path"]: c for c in obj["changed"]}
    assert "library.shelf.0.book.1.title" in changed
    assert changed["library.shelf.0.book.1.title"]["b"] == "Harbor Nights"


def test_xml_attribute_change(fixtures: Path, tmp_path: Path):
    modified = tmp_path / "sample.xml"
    modified.write_text(
        (fixtures / "sample.xml").read_text().replace('<shelf id="C">', '<shelf id="Z">')
    )
    code, obj = diff_json(str(fixtures / "sample.xml"), str(modified))
    assert code == 1
    assert any(c["path"].endswith(".@id") for c in obj["changed"])


# ------------------------------------------------------------------ pdf mode


@needs("pdftotext")
def test_pdf_pair_text_diff_nonempty(fixtures: Path):
    code, obj = diff_json(str(fixtures / "text+image.pdf"), str(fixtures / "b.pdf"))
    assert code == 1
    assert obj["mode"] == "pdf"
    assert obj["identical"] is False
    assert obj["pages"] == {"a": 2, "b": 1}
    assert "palimpsest harbor" in obj["diff"]
    assert "second fiddle harbor" in obj["diff"]


@needs("pdftotext")
def test_pdf_identical(fixtures: Path):
    code, obj = diff_json(str(fixtures / "b.pdf"), str(fixtures / "b.pdf"))
    assert code == 0
    assert obj["identical"] is True


# ---------------------------------------------------------------- image mode


def test_image_identical_copies(fixtures: Path):
    code, obj = diff_json(str(fixtures / "sample.jpg"), str(fixtures / "sample-copy.jpg"))
    assert code == 0
    assert obj["mode"] == "image"
    assert obj["identical"] is True
    assert obj["pixel_diff_percent"] == 0
    assert obj["size_mismatch"] is False


def test_image_size_mismatch_padded(fixtures: Path):
    code, obj = diff_json(str(fixtures / "sample.jpg"), str(fixtures / "sample-resized.jpg"))
    assert code == 1
    assert obj["size_mismatch"] is True
    assert obj["size_a"] == [400, 300] and obj["size_b"] == [300, 225]
    assert obj["canvas"] == [400, 300]
    assert obj["pixel_diff_percent"] > 0
    assert obj["identical"] is False


def test_image_pixel_percentage_and_mean_delta(fixtures: Path, tmp_path: Path):
    modified = tmp_path / "modified.png"
    with Image.open(fixtures / "sample.png") as im:
        img = im.copy()
    ImageDraw.Draw(img).rectangle((0, 0, 99, 99), fill=(255, 0, 0))
    img.save(modified)
    code, obj = diff_json(str(fixtures / "sample.png"), str(modified))
    assert code == 1
    assert 0 < obj["pixel_diff_percent"] < 100
    # 100x100 box on a 400x300 canvas ≈ 8.33% (allow a little slack)
    assert obj["pixels_changed"] >= 100 * 100
    assert set(obj["mean_channel_delta"]) == {"r", "g", "b", "a"}
    assert obj["mean_channel_delta"]["r"] > 0
    assert obj["mean_channel_delta"]["a"] == 0


def test_image_heatmap_written(fixtures: Path, tmp_path: Path):
    heat = tmp_path / "heatmap.png"
    code, obj = diff_json(
        str(fixtures / "sample.jpg"), str(fixtures / "sample-resized.jpg"), "--out", str(heat)
    )
    assert code == 1
    assert obj["heatmap"] == str(heat)
    with Image.open(heat) as im:
        assert im.format == "PNG"
        assert list(im.size) == obj["canvas"]


def test_out_rejected_outside_image_mode(fixtures: Path, tmp_path: Path):
    res = run(
        "diff",
        str(fixtures / "sample.txt"),
        str(fixtures / "sample.md"),
        "--out",
        str(tmp_path / "x.png"),
    )
    assert res.exit_code == 4
    assert "image mode" in res.output


# ------------------------------------------------------------ errors & modes


def test_type_mismatch_exit_4(fixtures: Path):
    res = run("diff", str(fixtures / "sample.txt"), str(fixtures / "sample.png"))
    assert res.exit_code == 4


def test_forced_struct_mismatch_exit_4(fixtures: Path):
    res = run(
        "diff", str(fixtures / "sample.json"), str(fixtures / "sample.csv"), "--mode", "struct"
    )
    assert res.exit_code == 4


def test_missing_file_exit_4(fixtures: Path, tmp_path: Path):
    res = run("diff", str(fixtures / "sample.txt"), str(tmp_path / "nope.txt"))
    assert res.exit_code == 4


def test_help_documents_exit_codes(fixtures: Path):
    res = run("diff", "--help")
    assert res.exit_code == 0
    assert "identical" in res.output and "differ" in res.output
    assert "--mode" in res.output and "--out" in res.output


# ------------------------------------------------------------------- library


def test_diff_files_library_api(fixtures: Path):
    result = diff_files(fixtures / "sample.txt", fixtures / "sample.txt")
    assert result["identical"] is True
    assert result["mode"] == "text"
    with pytest.raises(CarrelInputError):
        diff_files(fixtures / "sample.txt", fixtures / "missing.txt")
    with pytest.raises(CarrelInputError):
        diff_files(fixtures / "sample.txt", fixtures / "sample.txt", mode="bogus")
