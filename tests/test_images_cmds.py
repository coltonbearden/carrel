"""Tests for `carrel thumb`, `extract-images`, `proof`, `color` (spec 07)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs
from PIL import Image

from carrel.cli import cli
from carrel.commands.color import contrast_ratio, convert_profile, palette_colors
from carrel.commands.extract_images import extract_images_file
from carrel.commands.proof import BUILTIN_PROFILES, proof_file, resolve_profile
from carrel.core.output import CarrelInputError

HEX_RE = re.compile(r"#[0-9a-f]{6}\Z")


def run(*args: str) -> CliRunner.Result:
    return CliRunner().invoke(cli, list(args))


def all_output(res) -> str:
    try:
        return res.output + res.stderr
    except (ValueError, AttributeError):
        return res.output


def _alias_resolves(alias: str) -> bool:
    try:
        resolve_profile(alias)
        return True
    except CarrelInputError:
        return False


def needs_profile(alias: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(
        not _alias_resolves(alias),
        reason=f"no ICC profile resolvable for alias '{alias}' on this system",
    )


# ===================================================================== thumb


def test_thumb_help():
    res = run("thumb", "--help")
    assert res.exit_code == 0
    for flag in ("--size", "--out-dir", "--format"):
        assert flag in res.output


def test_thumb_png_fits_size_and_keeps_aspect(tmp_copy, tmp_path: Path):
    """Acceptance: thumb on the png fixture is sized <= --size."""
    src = tmp_copy("sample.png")  # 400x300
    out = tmp_path / "thumbs"
    res = run("--json", "thumb", str(src), "--size", "64", "--out-dir", str(out))
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)[0]
    assert rec["src"] == str(src)
    assert rec["w"] <= 64 and rec["h"] <= 64
    assert (rec["w"], rec["h"]) == (64, 48)  # 4:3 preserved
    with Image.open(rec["thumb"]) as im:
        assert im.format == "PNG" and im.size == (64, 48)


def test_thumb_jpg_format(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.png")
    out = tmp_path / "thumbs"
    res = run(
        "--json", "thumb", str(src), "--format", "jpg", "--out-dir", str(out), "--size", "100"
    )
    assert res.exit_code == 0, all_output(res)
    thumb = Path(json.loads(res.stdout)[0]["thumb"])
    assert thumb.suffix == ".jpg"
    assert thumb.read_bytes().startswith(b"\xff\xd8\xff")


def test_thumb_ico_uses_largest_frame(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.ico")  # frames 16/32/48
    rec = json.loads(run("--json", "thumb", str(src), "--out-dir", str(tmp_path / "t")).stdout)[0]
    assert (rec["w"], rec["h"]) == (48, 48)  # largest frame, never upscaled


def test_thumb_never_upscales_images(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.png")  # 400x300
    rec = json.loads(
        run("--json", "thumb", str(src), "--size", "9999", "--out-dir", str(tmp_path / "t")).stdout
    )[0]
    assert (rec["w"], rec["h"]) == (400, 300)


@needs("pdftoppm")
def test_thumb_pdf_first_page(tmp_copy, tmp_path: Path):
    """Acceptance: thumb on the pdf fixture is sized <= --size."""
    src = tmp_copy("text+image.pdf")
    out = tmp_path / "thumbs"
    res = run("--json", "thumb", str(src), "--size", "128", "--out-dir", str(out))
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)[0]
    assert max(rec["w"], rec["h"]) == 128
    assert Path(rec["thumb"]).read_bytes().startswith(b"\x89PNG")


@needs("weasyprint")
@needs("pdftoppm")
def test_thumb_html_chain(tmp_copy, tmp_path: Path):
    tmp_copy("sample.png")  # sample.html references it relatively
    src = tmp_copy("sample.html")
    res = run("--json", "thumb", str(src), "--size", "120", "--out-dir", str(tmp_path / "thumbs"))
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)[0]
    assert max(rec["w"], rec["h"]) <= 120
    assert Path(rec["thumb"]).exists()


def test_thumb_multiple_sources(tmp_copy, tmp_path: Path):
    a, b = tmp_copy("sample.png"), tmp_copy("sample.jpg")
    res = run(
        "--json", "thumb", str(a), str(b), "--size", "50", "--out-dir", str(tmp_path / "thumbs")
    )
    assert res.exit_code == 0, all_output(res)
    recs = json.loads(res.stdout)
    assert len(recs) == 2
    assert all(Path(r["thumb"]).exists() and r["w"] <= 50 for r in recs)


def test_thumb_unsupported_type_exits_4(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    res = run("thumb", str(src), "--out-dir", str(tmp_path / "t"))
    assert res.exit_code == 4
    assert "cannot thumbnail" in all_output(res)


def test_thumb_missing_file_exits_4(tmp_path: Path):
    res = run("thumb", str(tmp_path / "nope.png"), "--out-dir", str(tmp_path / "t"))
    assert res.exit_code == 4
    assert "no such file" in all_output(res)


def test_thumb_batch_continues_after_failure(tmp_copy, tmp_path: Path):
    bad, good = tmp_copy("sample.txt"), tmp_copy("sample.png")
    res = run("--json", "thumb", str(bad), str(good), "--out-dir", str(tmp_path / "t"))
    assert res.exit_code == 4  # first failure's code, batch still finished
    recs = json.loads(res.stdout)
    assert recs[0]["thumb"] is None and "error" in recs[0]
    assert Path(recs[1]["thumb"]).exists()


def test_thumb_file_library_api(tmp_copy, tmp_path: Path):
    from carrel.commands.thumb import thumb_file

    src = tmp_copy("sample.jpg")
    rec = thumb_file(src, tmp_path / "made" / "here", size=40, fmt="png")
    assert set(rec) == {"src", "thumb", "w", "h"}
    assert Path(rec["thumb"]).exists() and rec["w"] <= 40 and rec["h"] <= 40
    with pytest.raises(CarrelInputError):
        thumb_file(src, tmp_path, fmt="webp")


# ============================================================ extract-images


def test_extract_images_help():
    res = run("extract-images", "--help")
    assert res.exit_code == 0
    assert "--min-size" in res.output and "--out-dir" in res.output


@needs("pdfimages")
def test_extract_pdf_yields_pngs(tmp_copy, tmp_path: Path):
    """Acceptance: extract-images on the fixture pdf produces >=1 png."""
    src = tmp_copy("text+image.pdf")  # embeds a 400x300 PNG
    out = tmp_path / "imgs"
    res = run("--json", "extract-images", str(src), "--out-dir", str(out))
    assert res.exit_code == 0, all_output(res)
    data = json.loads(res.stdout)
    assert data["count"] >= 1 and len(data["extracted"]) == data["count"]
    for path in data["extracted"]:
        with Image.open(path) as im:
            assert im.format == "PNG"
            assert min(im.size) >= 32  # default --min-size honored


@needs("pdfimages")
def test_extract_pdf_min_size_filters_everything(tmp_copy, tmp_path: Path):
    src = tmp_copy("text+image.pdf")
    out = tmp_path / "imgs"
    res = run("--json", "extract-images", str(src), "--out-dir", str(out), "--min-size", "5000")
    assert res.exit_code == 0, all_output(res)
    data = json.loads(res.stdout)
    assert data["count"] == 0
    assert not list(out.glob("*.png"))  # filtered files really removed


@needs("icotool")
def test_extract_ico_via_icotool(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.ico")
    res = run("--json", "extract-images", str(src), "--out-dir", str(tmp_path / "i"))
    assert res.exit_code == 0, all_output(res)
    data = json.loads(res.stdout)
    assert data["count"] >= 1
    assert all(Path(p).exists() for p in data["extracted"])


def test_extract_ico_pillow_fallback(tmp_copy, tmp_path: Path, monkeypatch):
    """When icotool is absent we degrade to a Pillow frame dump."""
    from carrel.commands import extract_images as mod

    monkeypatch.setattr(mod.adapters, "have", lambda name: False)
    src = tmp_copy("sample.ico")  # frames 16/32/48
    data = extract_images_file(src, tmp_path / "frames")
    assert data["count"] == 3
    sizes = set()
    for path in data["extracted"]:
        with Image.open(path) as im:
            assert im.format == "PNG"
            sizes.add(im.size)
    assert sizes == {(16, 16), (32, 32), (48, 48)}


def test_extract_html_copies_only_local_existing(tmp_path: Path, fixtures: Path):
    import shutil

    shutil.copy2(fixtures / "sample.png", tmp_path / "art.png")
    page = tmp_path / "page.html"
    page.write_text(
        "<html><body>"
        '<img src="art.png">'
        '<img src="art.png">'  # duplicate → copied once
        '<img src="missing.png">'  # doesn\'t exist → skipped
        '<img src="https://example.com/remote.png">'  # remote → never fetched
        '<img src="//cdn.example.com/x.png">'
        '<img src="data:image/png;base64,AAAA">'
        "</body></html>"
    )
    out = tmp_path / "found"
    data = extract_images_file(page, out)
    assert data["count"] == 1
    assert data["extracted"] == [str(out / "art.png")]
    assert (out / "art.png").read_bytes() == (tmp_path / "art.png").read_bytes()


def test_extract_html_fixture_finds_sample_png(tmp_copy, tmp_path: Path):
    tmp_copy("sample.png")
    src = tmp_copy("sample.html")  # references sample.png relatively
    res = run("--json", "extract-images", str(src), "--out-dir", str(tmp_path / "o"))
    assert res.exit_code == 0, all_output(res)
    data = json.loads(res.stdout)
    assert data["count"] == 1
    assert Path(data["extracted"][0]).name == "sample.png"


def test_extract_default_out_dir_next_to_source(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.html")  # its img target doesn't exist here: 0 results
    data = extract_images_file(src)
    assert data["out_dir"] == str(tmp_path / "sample-images")
    assert Path(data["out_dir"]).is_dir()
    assert data["count"] == 0


def test_extract_unsupported_type_exits_4(tmp_copy):
    res = run("extract-images", str(tmp_copy("sample.txt")))
    assert res.exit_code == 4
    assert "supported: pdf, ico, html" in all_output(res)


# ===================================================================== proof


def test_proof_help():
    res = run("proof", "--help")
    assert res.exit_code == 0
    for token in ("--profile", "--intent", "--out", "cmyk"):
        assert token in res.output


@needs_profile("srgb")
def test_resolve_profile_alias_and_path():
    path = resolve_profile("srgb")
    assert path.is_file() and path.suffix.lower() in (".icc", ".icm")
    assert resolve_profile(str(path)) == path  # explicit path passthrough


def test_resolve_profile_unknown_alias_lists_aliases():
    with pytest.raises(CarrelInputError) as exc:
        resolve_profile("bogus")
    for alias in BUILTIN_PROFILES:
        assert alias in str(exc.value)


def test_resolve_profile_missing_path_exits_4(tmp_path: Path):
    with pytest.raises(CarrelInputError, match="not found"):
        resolve_profile(str(tmp_path / "ghost.icc"))


@needs_profile("cmyk")
def test_proof_cmyk_alias_reports_deltas(tmp_path: Path):
    """Acceptance: proof with the cmyk alias runs and reports deltas."""
    src = tmp_path / "vivid.png"
    Image.new("RGB", (64, 64), (0, 255, 60)).save(src)  # far out of CMYK gamut
    res = run("--json", "proof", str(src), "--profile", "cmyk")
    assert res.exit_code == 0, all_output(res)
    report = json.loads(res.stdout)
    assert report["intent"] == "perceptual"
    assert report["profile"].endswith((".icc", ".ICC"))
    assert report["mean_delta"] > 0
    assert report["max_delta"] >= report["mean_delta"]
    assert 0 < report["pct_pixels_changed"] <= 100
    out = Path(report["out"])
    assert out == src.with_name("vivid.proof.png") and out.exists()
    with Image.open(out) as im:
        assert im.size == (64, 64) and im.mode == "RGB"


@needs_profile("cmyk")
def test_proof_relative_intent_and_out_path(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.jpg")
    out = tmp_path / "proofed.jpg"
    report = proof_file(src, "cmyk", out=out, intent="relative")
    assert report["intent"] == "relative"
    assert out.read_bytes().startswith(b"\xff\xd8\xff")  # honored .jpg suffix


def test_proof_unknown_alias_exits_4(tmp_copy):
    res = run("proof", str(tmp_copy("sample.png")), "--profile", "wonderland")
    assert res.exit_code == 4
    assert "builtin aliases" in all_output(res)


def test_proof_non_image_exits_4(tmp_copy):
    res = run("proof", str(tmp_copy("sample.txt")), "--profile", "srgb")
    assert res.exit_code == 4
    assert "raster image" in all_output(res)


# ===================================================================== color


def test_color_group_help_lists_subcommands():
    res = run("color", "--help")
    assert res.exit_code == 0
    for sub in ("palette", "convert", "check"):
        assert sub in res.output


def test_palette_returns_n_colors_summing_to_one(tmp_copy):
    """Acceptance: palette returns n hex colors with proportions ~1.0."""
    src = tmp_copy("sample.jpg")
    res = run("--json", "color", "palette", str(src), "--n", "8")
    assert res.exit_code == 0, all_output(res)
    entries = json.loads(res.stdout)
    assert len(entries) == 8
    for entry in entries:
        assert HEX_RE.match(entry["hex"])
        assert 0 < entry["proportion"] <= 1
    assert sum(e["proportion"] for e in entries) == pytest.approx(1.0, abs=0.01)
    props = [e["proportion"] for e in entries]
    assert props == sorted(props, reverse=True)  # dominant first


def test_palette_small_n_library_api(tmp_copy):
    entries = palette_colors(tmp_copy("sample.png"), n=3)
    assert len(entries) == 3
    assert all(HEX_RE.match(e["hex"]) for e in entries)


def test_palette_non_image_exits_4(tmp_copy):
    res = run("color", "palette", str(tmp_copy("sample.csv")))
    assert res.exit_code == 4


@needs_profile("cmyk")
def test_color_convert_cmyk_embeds_profile(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.png")
    res = run("--json", "color", "convert", str(src), "--to-profile", "cmyk")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)
    out = Path(rec["out"])
    assert rec["mode"] == "CMYK" and out.suffix == ".jpg" and "cmyk" in out.name
    with Image.open(out) as im:
        assert im.mode == "CMYK"
        assert im.info.get("icc_profile")  # profile embedded
    assert im.info["icc_profile"] == Path(rec["profile"]).read_bytes()


@needs_profile("srgb")
def test_color_convert_srgb_png_out(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.jpg")
    out = tmp_path / "srgb-tagged.png"
    rec = convert_profile(src, "srgb", out=out)
    assert rec["mode"] == "RGB" and rec["ok"] is True
    with Image.open(out) as im:
        assert im.format == "PNG" and im.mode == "RGB"
        assert im.info.get("icc_profile")


@needs_profile("cmyk")
def test_color_convert_cmyk_refuses_png_out(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.png")
    res = run("color", "convert", str(src), "--to-profile", "cmyk", "-o", str(tmp_path / "bad.png"))
    assert res.exit_code == 4
    assert "CMYK" in all_output(res)


def test_contrast_black_on_white_is_21(tmp_path: Path):
    """Acceptance: contrast of #000 on #fff is 21."""
    res = run("--json", "color", "check", "#000", "#fff")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)
    assert rec["ratio"] == 21.0
    assert rec["fg"] == "#000000" and rec["bg"] == "#ffffff"
    assert all(rec[k] for k in ("aa_normal", "aa_large", "aaa_normal", "aaa_large"))
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)


def test_contrast_low_pair_fails_aa():
    res = run("--json", "color", "check", "777", "999")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)
    assert rec["ratio"] < 3.0
    assert not rec["aa_normal"] and not rec["aaa_normal"]


def test_contrast_bad_hex_is_usage_error():
    res = run("color", "check", "#12345", "#fff")
    assert res.exit_code == 2
    assert "hex color" in all_output(res)


# ------------------------------------------------------------- subprocess


def test_subprocess_real_cli_thumb(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.png")
    out = tmp_path / "thumbs"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "carrel.cli",
            "--json",
            "thumb",
            str(src),
            "--size",
            "32",
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    rec = json.loads(proc.stdout)[0]
    assert rec["w"] <= 32 and rec["h"] <= 32
    assert Path(rec["thumb"]).exists()
