#!/usr/bin/env python3
"""Build, pack and smoke-test the Claude Desktop extension (an MCP Bundle, `.mcpb`) — D-030.

    uv run python scripts/build_mcpb.py stage   [--out DIR]
    uv run python scripts/build_mcpb.py pack    [--out DIR] [--mcpb PATH]
    uv run python scripts/build_mcpb.py smoke FILE --runtime checkout|pypi [--docs DIR] [--retry-for SECONDS]

The bundle is manifest 0.4 with `server.type: "uv"`: it ships a `pyproject.toml` naming the
package at this version, and the host's own uv installs Python and the dependencies on the
user's machine. Nothing third-party is inside the file, and no lock: the dependencies resolve
when the extension is installed, never frozen here.

Everything that identifies the product comes from `product.json` (name, display name, version,
tagline, description, author, license, repository) and `pyproject.toml` (URLs, keywords,
requires-python, the newest classified Python). The tool list is the server's own registry,
`carrel.commands.mcp.TOOLS`. Nothing generated here is committed, so nothing can drift.

`pack` needs Node and the MCPB CLI locked in `packaging/mcpb/` (`npm ci --prefix packaging/mcpb`).
`stage` and `smoke` need neither, which is how tests/test_mcpb.py runs in every CI job.

`smoke` unpacks a built `.mcpb` and talks MCP to it over stdio: `initialize`, `tools/list` and
`carrel_doctor`.
- `--runtime checkout` runs the bundle's launcher with this checkout's Python, so it proves the
  packed launcher and manifest against the code under review.
- `--runtime pypi` runs the manifest's own `mcp_config` (`uv run --directory <bundle> ...`), so uv
  installs the pinned version from PyPI exactly as Desktop does. It is the release path: on a
  pull request the pin names the last release, so it only holds once that version is published.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "packaging" / "mcpb" / "server.py"
ICON = ROOT / "assets" / "icon-512.png"
MCPB_BIN = ROOT / "packaging" / "mcpb" / "node_modules" / ".bin" / "mcpb"
DEFAULT_OUT = ROOT / "build" / "mcpb"

MANIFEST_VERSION = "0.4"
ENTRY_POINT = "src/server.py"
FOLDER_KEY = "documents_folder"
#: Extras the bundle installs. `office` reads spreadsheets. Left out (D-030): `tui`, a terminal
#: UI with no use in Desktop, and `tokens`, whose tiktoken fetches its table from a third-party
#: host on first use while `pack` counts by estimate without it.
EXTRAS = ("office",)
#: Variables from the caller that would change how the bundle's uv runs. A host starts the server
#: with none of them; CI sets UV_LOCKED=1, which `uv run` in a directory with no lock refuses.
CALLER_UV_ENV = ("UV_LOCKED", "UV_FROZEN", "UV_NO_SYNC", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV")
PROTOCOL_VERSION = "2025-06-18"


def _product() -> dict[str, Any]:
    return json.loads((ROOT / "product.json").read_text(encoding="utf-8"))


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def newest_classified_python(classifiers: list[str]) -> str:
    """The newest `Programming Language :: Python :: 3.N` classifier, compared as numbers."""
    found = [
        (int(m[1]), int(m[2]))
        for c in classifiers
        if (m := re.fullmatch(r"Programming Language :: Python :: (\d+)\.(\d+)", c.strip()))
    ]
    if not found:
        raise SystemExit("pyproject.toml has no 'Programming Language :: Python :: X.Y' classifier")
    major, minor = max(found)
    return f"{major}.{minor}"


def _tools() -> list[dict[str, str]]:
    sys.path.insert(0, str(ROOT / "src"))
    from carrel.commands.mcp import TOOLS

    return [{"name": t["name"], "description": t["description"]} for t in TOOLS]


def manifest(product: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    """The bundle's manifest.json, from product.json, pyproject.toml and the tool registry."""
    urls = project["urls"]
    owner_url = product["repository"].rsplit("/", 1)[0]
    floor = re.fullmatch(r">=\s*(\d+\.\d+)", project["requires-python"].strip())
    if not floor:
        raise SystemExit(f"requires-python {project['requires-python']!r} is not a plain '>=X.Y'")
    return {
        "manifest_version": MANIFEST_VERSION,
        "name": product["name"],
        "display_name": product["displayName"],
        "version": product["version"],
        "description": product["tagline"],
        "long_description": product["description"],
        "author": {"name": product["author"], "url": owner_url},
        "repository": {"type": "git", "url": product["repository"]},
        "homepage": urls["Homepage"],
        "documentation": urls["Documentation"],
        "support": urls["Issues"],
        "icon": "icon.png",
        "server": {
            "type": "uv",
            "entry_point": ENTRY_POINT,
            # The strict 0.4 schema still requires mcp_config for uv servers (mcpb#263);
            # this is the shape of the format's own examples/hello-world-uv.
            "mcp_config": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    "${__dirname}",
                    ENTRY_POINT,
                    f"${{user_config.{FOLDER_KEY}}}",
                ],
            },
        },
        "tools": _tools(),
        "tools_generated": False,
        "prompts_generated": False,
        "keywords": list(project.get("keywords", [])),
        "license": product["license"],
        "compatibility": {
            "platforms": ["darwin", "win32", "linux"],
            "runtimes": {"python": f">={floor[1]}"},
        },
        "user_config": {
            FOLDER_KEY: {
                "type": "directory",
                "title": "Documents folder",
                "description": (
                    "The one folder the extension may use. It reads and writes only inside it, "
                    "and keeps its search index in a .carrel folder there."
                ),
                "required": True,
            }
        },
    }


def bundle_pyproject(product: dict[str, Any], project: dict[str, Any]) -> str:
    extras = ",".join(EXTRAS)
    return (
        "# Generated by scripts/build_mcpb.py. The host's uv installs these on the user's machine.\n"
        "[project]\n"
        f'name = "{product["package"]}-desktop-extension"\n'
        f'version = "{product["version"]}"\n'
        f'description = "Claude Desktop extension: runs {product["cli"]} mcp on one folder"\n'
        f'requires-python = "{project["requires-python"]}"\n'
        f'dependencies = ["{product["package"]}[{extras}]=={product["version"]}"]\n'
        "\n"
        "[tool.uv]\n"
        "package = false\n"
    )


def stage(out: Path) -> Path:
    """Write the bundle's folder under `out` and return it."""
    product, project = _product(), _pyproject()
    folder = out / "stage"
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "src").mkdir(parents=True)
    data = manifest(product, project)
    (folder / "manifest.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (folder / "pyproject.toml").write_text(
        bundle_pyproject(product, project), encoding="utf-8", newline="\n"
    )
    (folder / ".python-version").write_text(
        newest_classified_python(project["classifiers"]) + "\n", encoding="utf-8", newline="\n"
    )
    # What a local `uv run` inside the folder leaves behind, as the format's uv example ignores.
    (folder / ".mcpbignore").write_text(".venv/\nuv.lock\n", encoding="utf-8", newline="\n")
    shutil.copyfile(LAUNCHER, folder / ENTRY_POINT)
    shutil.copyfile(ICON, folder / "icon.png")
    shutil.copyfile(ROOT / "LICENSE", folder / "LICENSE")
    return folder


def _mcpb(binary: Path, *args: str) -> None:
    proc = subprocess.run([str(binary), *args], check=False)
    if proc.returncode != 0:
        raise SystemExit(f"mcpb {args[0]} failed (exit {proc.returncode})")


def pack(out: Path, binary: Path) -> Path:
    if not binary.exists():
        print(
            f"the MCPB CLI is not installed at {binary}: run `npm ci --prefix packaging/mcpb`",
            file=sys.stderr,
        )
        raise SystemExit(3)
    folder = stage(out)
    product = _product()
    target = out / f"{product['package']}-{product['version']}.mcpb"
    target.unlink(missing_ok=True)
    _mcpb(binary, "validate", str(folder / "manifest.json"))
    _mcpb(binary, "pack", str(folder), str(target))
    _mcpb(binary, "info", str(target))
    print(f"wrote {target}")
    return target


def _messages() -> str:
    msgs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "build_mcpb-smoke", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "carrel_doctor", "arguments": {}},
        },
    ]
    return "".join(json.dumps(m) + "\n" for m in msgs)


def command(bundle: Path, docs: Path, runtime: str) -> list[str]:
    """How a host would start the unpacked bundle, from its own manifest."""
    data = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    config = data["server"]["mcp_config"]
    subst = {"${__dirname}": str(bundle), f"${{user_config.{FOLDER_KEY}}}": str(docs)}
    args = [subst.get(a, a) for a in config["args"]]
    if runtime == "pypi":
        return [config["command"], *args]
    # checkout: the bundle's launcher and arguments, run by the Python that has this checkout
    after = args[args.index(data["server"]["entry_point"]) + 1 :]
    return [sys.executable, str(bundle / data["server"]["entry_point"]), *after]


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in CALLER_UV_ENV}
    env["PYTHONUTF8"] = "1"
    return env


def run_bundle(bundle: Path, docs: Path, runtime: str, timeout: float) -> list[dict[str, Any]]:
    proc = subprocess.run(
        command(bundle, docs, runtime),
        input=_messages(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        env=_child_env(),
        cwd=tempfile.gettempdir(),  # never the checkout: the root must come from the argument
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"the server exited {proc.returncode}:\n{proc.stderr[-4000:]}")
    responses = []
    for line in proc.stdout.splitlines():
        obj = json.loads(line)  # anything on stdout that is not one JSON object is a broken stream
        if not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0":
            raise AssertionError(f"not a JSON-RPC message on stdout: {line[:200]}")
        responses.append(obj)
    return responses


def check(responses: list[dict[str, Any]], data: dict[str, Any], runtime: str) -> dict[str, Any]:
    """Assert the live server is the one the manifest describes; return counts for the log."""
    by_id = {r.get("id"): r for r in responses}
    for mid in (1, 2, 3):
        if mid not in by_id or "result" not in by_id[mid]:
            raise AssertionError(f"no result for request {mid}: {by_id.get(mid)}")
    info = by_id[1]["result"]["serverInfo"]
    if (info["name"], info["version"]) != (data["name"], data["version"]):
        raise AssertionError(f"serverInfo {info} is not {data['name']} {data['version']}")
    live = [
        {"name": t["name"], "description": t["description"]} for t in by_id[2]["result"]["tools"]
    ]
    if live != data["tools"]:
        raise AssertionError("tools/list differs from the manifest's tools")
    if runtime == "checkout" and live != _tools():
        raise AssertionError("tools/list differs from this checkout's TOOLS")
    doctor = by_id[3]["result"]
    if doctor.get("isError"):
        raise AssertionError(
            f"carrel_doctor returned an error: {doctor['content'][0]['text'][:500]}"
        )
    report = json.loads(doctor["content"][0]["text"])
    adapters = report.get("adapters", [])
    return {
        "server": f"{info['name']} {info['version']}",
        "tools": len(live),
        "python": report.get("python"),
        "adapters found": f"{sum(1 for a in adapters if a.get('found'))}/{len(adapters)}",
    }


def smoke(file: Path, runtime: str, docs: Path | None, retry_for: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mcpb-smoke-") as tmp:
        bundle = Path(tmp) / "bundle"
        with zipfile.ZipFile(file) as zf:
            zf.extractall(bundle)
        data = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        if docs is None:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (docs / "note.txt").write_text("a smoke-test document\n", encoding="utf-8")
        deadline = time.monotonic() + retry_for
        while True:
            try:
                responses = run_bundle(bundle, docs.resolve(), runtime, timeout=900)
                break
            except RuntimeError as e:
                # A just-published release can take a minute to reach PyPI's index.
                if runtime != "pypi" or time.monotonic() >= deadline:
                    raise
                print(
                    f"not ready yet, retrying in 30 s: {str(e).splitlines()[-1][:200]}",
                    file=sys.stderr,
                )
                time.sleep(30)
        return check(responses, data, runtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_stage = sub.add_parser("stage", help="write the bundle folder (no Node needed)")
    p_stage.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p_pack = sub.add_parser(
        "pack", help="stage, validate and pack into OUT/<package>-<version>.mcpb"
    )
    p_pack.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p_pack.add_argument("--mcpb", type=Path, default=MCPB_BIN, help="the MCPB CLI binary")
    p_smoke = sub.add_parser("smoke", help="unpack a .mcpb and talk MCP to it")
    p_smoke.add_argument("file", type=Path)
    p_smoke.add_argument("--runtime", choices=("checkout", "pypi"), required=True)
    p_smoke.add_argument(
        "--docs", type=Path, help="the documents folder (default: a temporary one)"
    )
    p_smoke.add_argument(
        "--retry-for", type=float, default=0.0, help="pypi: keep retrying this many seconds"
    )
    args = parser.parse_args(argv)

    if args.cmd == "stage":
        print(f"staged {stage(args.out)}")
    elif args.cmd == "pack":
        pack(args.out, args.mcpb)
    else:
        result = smoke(args.file, args.runtime, args.docs, args.retry_for)
        print("smoke ok: " + ", ".join(f"{k} {v}" for k, v in result.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
