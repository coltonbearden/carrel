"""carrel color — palette extraction, ICC conversion, WCAG contrast.

A click group with three subcommands:

- palette: dominant colors via Pillow median-cut quantization.
- convert: convert an image into a target ICC profile (path or builtin
  alias, shared resolver with `carrel proof`) and embed the profile.
- check:   WCAG 2.x contrast ratio of two hex colors with AA/AAA verdicts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import click

from carrel.commands.proof import BUILTIN_PROFILES, _handled, load_image_cms, resolve_profile
from carrel.core.filetypes import detect_or_die
from carrel.core.output import CarrelInputError, emit

# WCAG 2.x minimum contrast ratios
AA_NORMAL, AA_LARGE, AAA_NORMAL, AAA_LARGE = 4.5, 3.0, 7.0, 4.5

#: ICC color space → Pillow mode (and a sensible default extension)
_SPACE_MODES = {"RGB": ("RGB", ".png"), "CMYK": ("CMYK", ".jpg"), "GRAY": ("L", ".png")}


@click.group(name="color")
def cmd() -> None:
    """Color tools: dominant palette, ICC profile conversion, WCAG contrast."""


# --------------------------------------------------------------------------
# palette


def palette_colors(src: Path | str, n: int = 8) -> list[dict[str, Any]]:
    """Dominant colors of an image: [{"hex", "proportion"}], largest first."""
    from PIL import Image

    src = Path(src)
    ftype = detect_or_die(src)
    if not ftype.is_image:
        raise CarrelInputError(
            f"palette needs a raster image (png/jpg/ico), got {ftype.value}: {src}"
        )
    with Image.open(src) as im:
        rgb = im.convert("RGB")
    quantized = rgb.quantize(colors=n)
    palette = quantized.getpalette() or []
    counts = quantized.getcolors(maxcolors=n) or []
    total = sum(count for count, _ in counts)
    entries = []
    for count, index in sorted(counts, reverse=True):
        i = cast("int", index)  # getcolors() on a "P" image yields palette indices
        r, g, b = palette[3 * i : 3 * i + 3]
        entries.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "proportion": round(count / total, 4)})
    return entries


def _palette_human(entries: list[dict[str, Any]]) -> None:
    from rich import print as rprint

    for entry in entries:
        swatch = f"[on {entry['hex']}]        [/]"
        rprint(f"{swatch} {entry['hex']}  {entry['proportion']:6.1%}")


@cmd.command(name="palette")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--n",
    type=click.IntRange(1, 256),
    default=8,
    show_default=True,
    help="Number of colors to extract.",
)
@click.pass_context
@_handled
def palette(ctx: click.Context, src: Path, n: int) -> None:
    """Dominant colors of SRC as hex + proportion (median-cut quantization).

    Human mode shows rich color swatches; --json prints one JSON array
    of {"hex", "proportion"} sorted by coverage.
    """
    emit(ctx, palette_colors(src, n=n), human=_palette_human)


# --------------------------------------------------------------------------
# convert


def convert_profile(
    src: Path | str, to_profile: str, out: Path | str | None = None
) -> dict[str, Any]:
    """Convert src into the target ICC profile and embed it in the output."""
    ImageCms = load_image_cms()  # noqa: N806 — module alias
    from PIL import Image

    src = Path(src)
    ftype = detect_or_die(src)
    if not ftype.is_image:
        raise CarrelInputError(
            f"color convert needs a raster image (png/jpg/ico), got {ftype.value}: {src}"
        )
    profile_path = resolve_profile(to_profile)
    target = ImageCms.getOpenProfile(str(profile_path))
    space = target.profile.xcolor_space.strip()
    if space not in _SPACE_MODES:
        raise CarrelInputError(
            f"unsupported profile color space '{space}' in "
            f"{profile_path.name} (supported: RGB, CMYK, GRAY)"
        )
    mode, default_ext = _SPACE_MODES[space]

    label = to_profile.lower() if to_profile.lower() in BUILTIN_PROFILES else profile_path.stem
    out = Path(out) if out else src.with_name(f"{src.stem}.{label}{default_ext}")
    if mode == "CMYK" and out.suffix.lower() not in (".jpg", ".jpeg", ".tif", ".tiff"):
        raise CarrelInputError(
            f"CMYK output cannot be saved as {out.suffix or out.name} — "
            "use a .jpg or .tif output path"
        )

    with Image.open(src) as im:
        rgb = im.convert("RGB")
    srgb = ImageCms.createProfile("sRGB")
    try:
        converted = ImageCms.profileToProfile(rgb, srgb, target, outputMode=mode)
    except ImageCms.PyCMSError as e:
        raise CarrelInputError(f"cannot convert to {profile_path.name}: {e}") from e
    out.parent.mkdir(parents=True, exist_ok=True)
    converted.save(out, icc_profile=profile_path.read_bytes())
    return {
        "src": str(src),
        "out": str(out),
        "profile": str(profile_path),
        "profile_name": ImageCms.getProfileName(target).strip(),
        "mode": mode,
        "ok": True,
    }


def _convert_human(result: dict[str, Any]) -> None:
    click.echo(f"{result['src']} -> {result['out']}  [{result['mode']}, {result['profile_name']}]")


@cmd.command(name="convert")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--to-profile",
    "to_profile",
    required=True,
    metavar="P",
    help="Target ICC profile: .icc path or builtin alias ("
    + ", ".join(sorted(BUILTIN_PROFILES))
    + ").",
)
@click.option(
    "-o",
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output path [default: <SRC>.<profile>.png/.jpg].",
)
@click.pass_context
@_handled
def convert(ctx: click.Context, src: Path, to_profile: str, out: Path | None) -> None:
    """Convert SRC into an ICC profile and embed the profile in the output.

    CMYK targets are written as JPEG/TIFF (PNG cannot store CMYK).
    """
    emit(ctx, convert_profile(src, to_profile, out=out), human=_convert_human)


# --------------------------------------------------------------------------
# check


def _parse_hex(color: str) -> tuple[int, int, int]:
    digits = color.strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if len(digits) != 6:
        raise ValueError(f"not a hex color: '{color}' (expected #rgb or #rrggbb)")
    try:
        value = int(digits, 16)
    except ValueError:
        raise ValueError(f"not a hex color: '{color}' (expected #rgb or #rrggbb)") from None
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def _luminance(rgb: tuple[int, int, int]) -> float:
    def lin(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio of two hex colors (1.0 .. 21.0)."""
    lums = sorted((_luminance(_parse_hex(fg)), _luminance(_parse_hex(bg))))
    return (lums[1] + 0.05) / (lums[0] + 0.05)


def _check_human(result: dict[str, Any]) -> None:
    verdict = {True: "PASS", False: "fail"}
    click.echo(f"{result['fg']} on {result['bg']}: contrast {result['ratio']}:1")
    click.echo(f"  AA  normal {verdict[result['aa_normal']]}   large {verdict[result['aa_large']]}")
    click.echo(
        f"  AAA normal {verdict[result['aaa_normal']]}   large {verdict[result['aaa_large']]}"
    )


@cmd.command(name="check")
@click.argument("fg")
@click.argument("bg")
@click.pass_context
def check(ctx: click.Context, fg: str, bg: str) -> None:
    """WCAG contrast ratio of FG on BG (hex colors, e.g. #333 #fafafa)."""
    try:
        ratio = contrast_ratio(fg, bg)
        fg_rgb, bg_rgb = _parse_hex(fg), _parse_hex(bg)
    except ValueError as e:
        raise click.UsageError(str(e)) from e
    result = {
        "fg": "#{:02x}{:02x}{:02x}".format(*fg_rgb),
        "bg": "#{:02x}{:02x}{:02x}".format(*bg_rgb),
        "ratio": round(ratio, 2),
        "aa_normal": ratio >= AA_NORMAL,
        "aa_large": ratio >= AA_LARGE,
        "aaa_normal": ratio >= AAA_NORMAL,
        "aaa_large": ratio >= AAA_LARGE,
    }
    emit(ctx, result, human=_check_human)
