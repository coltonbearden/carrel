# /// script
# requires-python = ">=3.12"
# dependencies = ["cairosvg"]
# ///
"""Render assets/logo.svg to assets/icon-512.png, the Claude Desktop extension's icon.

MCPB's `icon` must be a PNG, and `mcpb validate` recommends 512x512. Run this when
the logo changes and commit the result:

    uv run scripts/render_icon.py

uv reads the dependency block above and runs it in a throwaway environment, so
cairosvg never enters the project's lock. cairosvg needs the system cairo library
(libcairo2 on Debian/Ubuntu, `brew install cairo` on macOS). ImageMagick's
built-in SVG renderer is not a substitute: it drops the logo's stroked C and
paints the radial glow black. The bundle ships the committed file rather than
rendering one per build for the same reason, and tests/test_mcpb.py checks its
size.
"""

from __future__ import annotations

from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "logo.svg"
TARGET = ROOT / "assets" / "icon-512.png"
SIZE = 512


def main() -> None:
    cairosvg.svg2png(
        bytestring=SOURCE.read_bytes(),
        write_to=str(TARGET),
        output_width=SIZE,
        output_height=SIZE,
    )
    print(f"wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
