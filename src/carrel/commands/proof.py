"""carrel proof — ICC soft proofing via Pillow's ImageCms (LittleCMS).

Simulates how an sRGB image will look after a round trip through a
target profile (proof transform sRGB → profile → sRGB), writes the
proofed image, and reports how much changed.

PROFILE is either a path to an .icc/.icm file or one of the builtin
aliases (`cmyk`, `srgb`, `gray`, `p3`). Aliases resolve at runtime by
probing the system profile directories (/usr/share/color/icc and the
ghostscript iccprofiles dirs); an unresolvable alias exits 4 with the
list of profiles actually present.

`resolve_profile()` and `load_image_cms()` are shared with
`carrel color convert`.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core.filetypes import detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, emit, fail


def _handled(fn: Callable) -> Callable:
    """Convert CarrelError into a clean message + exit code (unless --debug)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = click.get_current_context(silent=True)
        try:
            return fn(*args, **kwargs)
        except CarrelError as e:
            if ctx is not None and ctx.obj and ctx.obj.get("debug"):
                raise
            fail(str(e), e.exit_code)

    return wrapper


#: per-channel delta (0-255) above which a pixel counts as "changed"
CHANGE_THRESHOLD = 8

INTENTS = {"perceptual": 0, "relative": 1}  # lcms INTENT_PERCEPTUAL / _RELATIVE_COLORIMETRIC

#: alias → candidate filenames (lowercase), first found wins
BUILTIN_PROFILES: dict[str, tuple[str, ...]] = {
    "cmyk": ("default_cmyk.icc", "ps_cmyk.icc"),
    "srgb": ("esrgb.icc", "srgb.icc", "srgb2014.icc", "srgb-v4.icc"),
    "gray": ("default_gray.icc", "sgray.icc", "gray-cie_l.icc", "sgrey-v4.icc"),
    "p3": ("dci-p3-d65.icc", "displayp3-v4.icc", "p3d65.icc", "dci-p3-v4.icc"),
}


class MissingLcmsError(CarrelError):
    """Pillow present but built without LittleCMS → exit 3."""

    exit_code = ExitCode.MISSING_DEP


def load_image_cms() -> Any:
    """PIL.ImageCms, or MissingLcmsError (exit 3) when LCMS is unavailable."""
    try:
        from PIL import ImageCms
    except ImportError as e:
        raise MissingLcmsError(
            "Pillow's ImageCms (LittleCMS) is unavailable — color management "
            "needs it.\n  install: uv pip install --force-reinstall pillow "
            "(official wheels bundle LittleCMS)"
        ) from e
    return ImageCms


def _profile_dirs() -> list[Path]:
    dirs = [Path("/usr/share/color/icc"), Path("/usr/share/color/icc/ghostscript")]
    dirs += sorted(Path("/usr/share/ghostscript").glob("*/iccprofiles"))
    return [d for d in dirs if d.is_dir()]


def installed_profiles() -> dict[str, Path]:
    """lowercase filename → path for every .icc/.icm on this system."""
    found: dict[str, Path] = {}
    for directory in _profile_dirs():
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() in (".icc", ".icm") and path.is_file():
                found.setdefault(path.name.lower(), path)
    return found


def resolve_profile(spec: str) -> Path:
    """PROFILE argument → concrete .icc path.

    Accepts a filesystem path or a builtin alias; raises CarrelInputError
    (exit 4) with actionable detail when neither resolves.
    """
    as_path = Path(spec)
    if as_path.suffix.lower() in (".icc", ".icm") or "/" in spec:
        if as_path.is_file():
            return as_path
        raise CarrelInputError(f"ICC profile not found: {spec}")
    alias = spec.lower()
    candidates = BUILTIN_PROFILES.get(alias)
    if candidates is None:
        raise CarrelInputError(
            f"unknown profile '{spec}' — pass a .icc file path or one of the "
            f"builtin aliases: {', '.join(sorted(BUILTIN_PROFILES))}"
        )
    found = installed_profiles()
    for name in candidates:
        if name in found:
            return found[name]
    listing = ", ".join(sorted(found)) if found else "none"
    raise CarrelInputError(
        f"alias '{alias}' matches none of the installed ICC profiles "
        f"(looked for: {', '.join(candidates)}).\n"
        f"  searched: {', '.join(str(d) for d in _profile_dirs()) or 'no profile dirs exist'}\n"
        f"  profiles found: {listing}\n"
        "  install: sudo apt install ghostscript icc-profiles-free"
    )


def _deltas(before: bytes, after: bytes) -> tuple[float, int, float]:
    """(mean abs channel delta, max delta, % pixels with any channel delta > threshold)."""
    diffs = [abs(a - b) for a, b in zip(before, after, strict=False)]
    n_px = len(diffs) // 3
    changed = sum(
        1
        for i in range(0, n_px * 3, 3)
        if max(diffs[i], diffs[i + 1], diffs[i + 2]) > CHANGE_THRESHOLD
    )
    return (
        sum(diffs) / len(diffs) if diffs else 0.0,
        max(diffs, default=0),
        100.0 * changed / n_px if n_px else 0.0,
    )


def proof_file(
    src: Path | str, profile: str, out: Path | str | None = None, intent: str = "perceptual"
) -> dict[str, Any]:
    """Soft-proof one image; writes the proofed copy and returns the report."""
    ImageCms = load_image_cms()  # noqa: N806 — module alias
    from PIL import Image

    src = Path(src)
    ftype = detect_or_die(src)
    if not ftype.is_image:
        raise CarrelInputError(
            f"proof needs a raster image (png/jpg/ico), got {ftype.value}: {src}"
        )
    profile_path = resolve_profile(profile)
    out = Path(out) if out else src.with_name(f"{src.stem}.proof.png")

    with Image.open(src) as im:
        rgb = im.convert("RGB")
    srgb = ImageCms.createProfile("sRGB")
    target = ImageCms.getOpenProfile(str(profile_path))
    try:
        transform = ImageCms.buildProofTransform(
            srgb,
            srgb,
            target,
            "RGB",
            "RGB",
            renderingIntent=INTENTS[intent],
            proofRenderingIntent=INTENTS[intent],
        )
        proofed = ImageCms.applyTransform(rgb, transform)
    except ImageCms.PyCMSError as e:
        raise CarrelInputError(f"cannot soft-proof against {profile_path.name}: {e}") from e

    out.parent.mkdir(parents=True, exist_ok=True)
    proofed.save(out, format="JPEG" if out.suffix.lower() in (".jpg", ".jpeg") else "PNG")

    mean_delta, max_delta, pct_changed = _deltas(rgb.tobytes(), proofed.tobytes())
    return {
        "src": str(src),
        "out": str(out),
        "profile": str(profile_path),
        "profile_name": ImageCms.getProfileName(target).strip(),
        "intent": intent,
        "mean_delta": round(mean_delta, 3),
        "max_delta": max_delta,
        "pct_pixels_changed": round(pct_changed, 2),
        "change_threshold": CHANGE_THRESHOLD,
    }


def _human(report: dict[str, Any]) -> None:
    click.echo(f"{report['src']} -> {report['out']}")
    click.echo(f"  profile: {report['profile_name']} ({report['profile']})")
    click.echo(f"  intent:  {report['intent']}")
    click.echo(
        f"  mean delta {report['mean_delta']}, max {report['max_delta']}, "
        f"{report['pct_pixels_changed']}% of pixels shifted more than "
        f"{report['change_threshold']}/255"
    )


@click.command(name="proof")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--profile",
    required=True,
    metavar="PROFILE",
    help="Path to a .icc file, or builtin alias: " + ", ".join(sorted(BUILTIN_PROFILES)) + ".",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Proofed image path [default: <SRC>.proof.png].",
)
@click.option(
    "--intent",
    type=click.Choice(sorted(INTENTS)),
    default="perceptual",
    show_default=True,
    help="Rendering intent.",
)
@click.pass_context
@_handled
def cmd(ctx: click.Context, src: Path, profile: str, out: Path | None, intent: str) -> None:
    """Soft-proof SRC against an ICC PROFILE (simulate print/display output).

    Writes the proofed image and reports the color shift: mean/max
    per-channel delta and the share of pixels that moved visibly. With
    --json, prints the report as one JSON object.
    """
    emit(ctx, proof_file(src, profile, out=out, intent=intent), human=_human)
