"""Entry point of the Claude Desktop extension (MCP Bundle): the stdlib plus the installed package.

Desktop runs this as `uv run --directory <extension dir> src/server.py <folder>`, where
<folder> is the one directory the user picked when installing (`user_config.documents_folder`
in manifest.json). It starts carrel's stdio MCP server confined to that folder:
`carrel --root <folder> mcp`.

It fails closed. A missing root would make carrel confine itself to whatever directory Desktop
started it in, so anything but exactly one absolute path to an existing directory exits 2 with
the reason on stderr and nothing on stdout (stdout is the JSON-RPC stream). The same goes for
the placeholder itself, which reaches the server unchanged if a host does not substitute it.

`scripts/build_mcpb.py` copies this file into the bundle as `src/server.py`; tests/test_mcpb.py
runs it. D-030 in docs/DECISIONS.md records why the bundle is shaped this way.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Exit code for bad usage, as carrel's own CLI uses it (CLAUDE.md, "Exit code convention").
USAGE = 2


def _refuse(reason: str) -> int:
    print(f"desktop extension: {reason}; nothing was started.", file=sys.stderr)
    return USAGE


def _folder(argv: list[str]) -> Path | str:
    """The documents folder, or the reason it cannot be used."""
    if len(argv) != 1:
        return f"expected exactly one argument, the documents folder, got {len(argv)}"
    raw = argv[0]
    if not raw.strip():
        return "the documents folder is empty; choose one in the extension's settings"
    if "${user_config." in raw:
        return "the documents folder was not filled in by the host; choose one in the extension's settings"
    folder = Path(raw)
    if not folder.is_absolute():
        return f"the documents folder must be an absolute path, got {raw!r}"
    if not folder.is_dir():
        return f"the documents folder {raw!r} does not exist or is not a directory"
    return folder


def main(argv: list[str] | None = None) -> int:
    folder = _folder(sys.argv[1:] if argv is None else argv)
    if isinstance(folder, str):
        return _refuse(folder)
    # Imported only once the folder is known good, so a refusal never pays carrel's import cost.
    from carrel.cli import main as carrel_main

    # carrel's main() reads sys.argv itself (for --debug and --json), so set it rather than pass it.
    sys.argv = ["carrel", "--root", str(folder), "mcp"]
    carrel_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
