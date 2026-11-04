"""The Claude Desktop extension (D-030): what scripts/build_mcpb.py stages, and the launcher it ships.

None of this needs Node. `stage` and `smoke --runtime checkout` are plain Python, so every CI job
runs these tests; the `bundle` job adds the MCPB CLI's own `validate` and `pack`.

The manifest's tools are held equal to this checkout's `TOOLS`, and the launcher's live
`tools/list` to both. Equality with the server PyPI serves is asserted only on the release path
(`publish.yml`'s `attach` job, `smoke --runtime pypi`): on a pull request the bundle's pin names
the last release, whose tools may differ from the code under review. Do not add that comparison
here when the tool set changes; the release path is where it holds.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from carrel._product import PRODUCT
from carrel.commands.mcp import TOOLS

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD = REPO_ROOT / "scripts" / "build_mcpb.py"
LAUNCHER = REPO_ROOT / "packaging" / "mcpb" / "server.py"

# The sdist ships tests/ but not scripts/, packaging/ or assets/.
pytestmark = pytest.mark.skipif(
    not BUILD.is_file() or not LAUNCHER.is_file(),
    reason="the bundle's sources are not part of the sdist",
)

TIMEOUT = 60


@pytest.fixture(scope="module")
def build_mcpb():
    spec = importlib.util.spec_from_file_location("build_mcpb", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def staged(build_mcpb, tmp_path) -> Path:
    return build_mcpb.stage(tmp_path / "out")


def _manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def _project() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


# --- the manifest -------------------------------------------------------------------------------


def test_identity_comes_from_product_json(staged):
    data = _manifest(staged)
    assert data["manifest_version"] == "0.4"
    assert (data["name"], data["display_name"], data["version"]) == (
        PRODUCT["name"],
        PRODUCT["displayName"],
        PRODUCT["version"],
    )
    assert data["description"] == PRODUCT["tagline"]
    assert data["long_description"] == PRODUCT["description"]
    assert data["author"]["name"] == PRODUCT["author"]
    assert data["license"] == PRODUCT["license"]
    assert data["repository"] == {"type": "git", "url": PRODUCT["repository"]}
    assert data["support"] == _project()["urls"]["Issues"]


def test_tools_are_the_servers_own(staged):
    data = _manifest(staged)
    assert data["tools"] == [{"name": t["name"], "description": t["description"]} for t in TOOLS]
    assert data["tools_generated"] is False


def test_one_required_folder_is_the_servers_root(staged):
    data = _manifest(staged)
    assert list(data["user_config"]) == ["documents_folder"]
    folder = data["user_config"]["documents_folder"]
    assert folder["type"] == "directory"
    assert folder["required"] is True
    assert "default" not in folder, "the user picks the folder; a default would choose one for them"
    assert "multiple" not in folder
    server = data["server"]
    assert server["type"] == "uv"
    args = server["mcp_config"]["args"]
    # the folder is a bare argument right after the launcher, so the host passes it whole
    assert args[args.index(server["entry_point"]) + 1 :] == ["${user_config.documents_folder}"]
    assert "--allow-outside-root" not in json.dumps(data)


def test_staged_files_are_the_launcher_icon_and_license(staged):
    data = _manifest(staged)
    assert (staged / data["server"]["entry_point"]).read_bytes() == LAUNCHER.read_bytes()
    assert (staged / "LICENSE").read_bytes() == (REPO_ROOT / "LICENSE").read_bytes()
    icon = (staged / data["icon"]).read_bytes()
    assert icon[:8] == b"\x89PNG\r\n\x1a\n", "MCPB requires a PNG icon"
    width, height = struct.unpack(">II", icon[16:24])  # IHDR follows the signature
    assert (width, height) == (512, 512)
    assert not (staged / "uv.lock").exists(), "a lock would freeze the dependencies (D-030)"
    assert sorted(p.name for p in staged.iterdir()) == sorted(
        [
            ".mcpbignore",
            ".python-version",
            "LICENSE",
            "icon.png",
            "manifest.json",
            "pyproject.toml",
            "src",
        ]
    )


def test_the_bundle_installs_this_version_from_pypi(staged):
    bundle = tomllib.loads((staged / "pyproject.toml").read_text(encoding="utf-8"))
    project = _project()
    assert bundle["project"]["dependencies"] == [
        f"{PRODUCT['package']}[office]=={PRODUCT['version']}"
    ]
    assert bundle["project"]["requires-python"] == project["requires-python"]
    assert bundle["tool"]["uv"]["package"] is False
    runtimes = _manifest(staged)["compatibility"]["runtimes"]
    assert runtimes == {"python": project["requires-python"].replace(" ", "")}


def test_python_version_is_the_newest_classified(staged, build_mcpb):
    pinned = (staged / ".python-version").read_text(encoding="utf-8").strip()
    assert pinned == build_mcpb.newest_classified_python(_project()["classifiers"])
    assert f"Programming Language :: Python :: {pinned}" in _project()["classifiers"]


def test_newest_classified_python_compares_as_numbers(build_mcpb):
    classifiers = [
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.14",
        "Programming Language :: Python :: 3.12",
    ]
    assert build_mcpb.newest_classified_python(classifiers) == "3.14"  # max() of strings says 3.9
    with pytest.raises(SystemExit):
        build_mcpb.newest_classified_python(["Programming Language :: Python :: 3"])


def test_the_smoke_starts_the_bundle_without_the_callers_uv_settings(build_mcpb, monkeypatch):
    """A host starts the bundle with none of them. CI sets UV_LOCKED=1 (refused in a folder
    with no lock) and setup-uv sets UV_PYTHON (which would override .python-version)."""
    for name in ("UV_LOCKED", "UV_PYTHON", "UV_FROZEN", "UV_SOMETHING_LATER", "VIRTUAL_ENV"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("CARREL_TEST_UNRELATED", "kept")
    env = build_mcpb._child_env()
    assert not [k for k in env if k.startswith("UV_") or k == "VIRTUAL_ENV"]
    assert env["CARREL_TEST_UNRELATED"] == "kept"


def test_the_pypi_runtime_is_the_manifests_command_refreshing_the_pin(build_mcpb, staged, tmp_path):
    cmd = build_mcpb.command(staged, tmp_path, "pypi")
    assert cmd == [
        "uv",
        "run",
        "--refresh-package",
        PRODUCT["package"],
        "--directory",
        str(staged),
        "src/server.py",
        str(tmp_path),
    ]


def test_the_pypi_runtime_must_run_on_the_bundles_python(build_mcpb, staged):
    data = _manifest(staged)
    responses = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"serverInfo": {"name": data["name"], "version": data["version"]}},
        },
        {"jsonrpc": "2.0", "id": 2, "result": {"tools": data["tools"]}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps({"python": "3.12.16", "adapters": []})}
                ]
            },
        },
    ]
    assert build_mcpb.check(responses, data, "pypi", "3.12")["python"] == "3.12.16"
    with pytest.raises(AssertionError, match=r"not the bundle's 3\.14"):
        build_mcpb.check(responses, data, "pypi", "3.14")


def test_only_a_version_missing_from_the_index_is_retried(
    build_mcpb, staged, tmp_path, monkeypatch
):
    bundle = _zip(staged, tmp_path / "b.mcpb")
    calls = []

    def fails_with(message):
        def fake(*args, **kwargs):
            calls.append(message)
            if len(calls) == 1:
                raise RuntimeError(message)
            return []

        return fake

    monkeypatch.setattr(build_mcpb.time, "sleep", lambda _s: None)
    monkeypatch.setattr(build_mcpb, "check", lambda *a: {"ok": True})
    monkeypatch.setattr(
        build_mcpb, "run_bundle", fails_with("No solution found when resolving dependencies")
    )
    assert build_mcpb.smoke(bundle, "pypi", None, 600) == {"ok": True}
    assert len(calls) == 2, "a version not on the index yet is retried"
    calls.clear()
    monkeypatch.setattr(
        build_mcpb, "run_bundle", fails_with("the server exited 2: desktop extension: refused")
    )
    with pytest.raises(RuntimeError, match="exited 2"):
        build_mcpb.smoke(bundle, "pypi", None, 600)
    assert len(calls) == 1, "a refusal or a crash fails at once"


def test_stage_will_not_delete_a_folder_it_did_not_write(build_mcpb, tmp_path):
    out = tmp_path / "out"
    (out / "stage").mkdir(parents=True)
    (out / "stage" / "precious.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(SystemExit, match="did not write"):
        build_mcpb.stage(out)
    assert (out / "stage" / "precious.txt").read_text(encoding="utf-8") == "keep me"
    (out / "stage" / "precious.txt").unlink()
    build_mcpb.stage(out)
    build_mcpb.stage(out)  # its own earlier output it replaces


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in CLI is a shell script")
def test_pack_leaves_one_bundle_in_its_folder(build_mcpb, tmp_path):
    fake = tmp_path / "mcpb"
    fake.write_text('#!/bin/sh\n[ "$1" = pack ] && : > "$3"\nexit 0\n', encoding="utf-8")
    fake.chmod(0o755)
    out = tmp_path / "out"
    out.mkdir()
    (out / f"{PRODUCT['package']}-0.0.1.mcpb").write_text("an older bundle", encoding="utf-8")
    target = build_mcpb.pack(out, fake)
    assert sorted(p.name for p in out.glob("*.mcpb")) == [target.name]


def test_pack_without_the_cli_exits_3(build_mcpb, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        build_mcpb.pack(tmp_path / "out", tmp_path / "no-such-mcpb")
    assert exc.value.code == 3
    assert "npm ci --prefix packaging/mcpb" in capsys.readouterr().err


# --- the launcher -------------------------------------------------------------------------------


def _launch(args: list[str], *, cwd: Path, messages: list[dict] | None = None):
    raw = "".join(json.dumps(m) + "\n" for m in messages or [])
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        input=raw,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT,
        cwd=cwd,
    )


def _responses(stdout: str) -> dict:
    out = {}
    for line in stdout.splitlines():
        obj = json.loads(line)  # every stdout line is one JSON-RPC message, nothing else
        assert obj["jsonrpc"] == "2.0", line
        out[obj.get("id")] = obj
    return out


def test_launcher_serves_the_folder_it_is_given(tmp_path):
    docs, elsewhere = tmp_path / "docs", tmp_path / "elsewhere"
    docs.mkdir()
    elsewhere.mkdir()
    (docs / "inside.txt").write_text("inside the folder\n", encoding="utf-8")
    (elsewhere / "outside.txt").write_text("not for the extension\n", encoding="utf-8")
    call = {"jsonrpc": "2.0", "method": "tools/call"}
    proc = _launch(
        [str(docs)],
        cwd=elsewhere,  # the root must come from the argument, never the working directory
        messages=[
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {
                **call,
                "id": 2,
                "params": {"name": "carrel_inspect", "arguments": {"path": "inside.txt"}},
            },
            {
                **call,
                "id": 3,
                "params": {
                    "name": "carrel_inspect",
                    "arguments": {"path": str(elsewhere / "outside.txt")},
                },
            },
        ],
    )
    assert proc.returncode == 0, proc.stderr
    got = _responses(proc.stdout)
    assert [t["name"] for t in got[1]["result"]["tools"]] == [t["name"] for t in TOOLS]
    assert not got[2]["result"].get("isError"), got[2]
    refused = got[3]["result"]
    assert refused["isError"] is True
    assert json.loads(refused["content"][0]["text"])["exit_code"] == 2
    assert "not for the extension" not in proc.stdout


def test_a_folder_whose_name_holds_a_dollar_brace_is_served(tmp_path):
    docs = tmp_path / "notes ${draft}"
    docs.mkdir()
    proc = _launch(
        [str(docs)], cwd=tmp_path, messages=[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
    )
    assert proc.returncode == 0, proc.stderr
    assert len(_responses(proc.stdout)[1]["result"]["tools"]) == len(TOOLS)


@pytest.mark.parametrize(
    ("make_args", "reason"),
    [
        (lambda tmp: [], "exactly one argument"),
        (lambda tmp: [str(tmp), str(tmp)], "exactly one argument"),
        (lambda tmp: [""], "empty"),
        (lambda tmp: ["${user_config.documents_folder}"], "not filled in"),
        (lambda tmp: ["docs"], "absolute path"),
        (lambda tmp: [str(tmp / "missing")], "does not exist"),
        (lambda tmp: [str(tmp / "file.txt")], "not a directory"),
    ],
    ids=["none", "two", "empty", "placeholder", "relative", "missing", "file"],
)
def test_launcher_refuses_anything_but_one_existing_folder(tmp_path, make_args, reason):
    (tmp_path / "docs").mkdir()  # so "docs" exists relative to cwd: refused for being relative
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    proc = _launch(
        make_args(tmp_path),
        cwd=tmp_path,
        messages=[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}],
    )
    assert proc.returncode == 2
    assert proc.stdout == "", "a refusal must not write to the JSON-RPC stream"
    assert reason in proc.stderr
    assert "nothing was started" in proc.stderr


# --- the smoke, end to end without Node ---------------------------------------------------------


def _zip(folder: Path, target: Path) -> Path:
    with zipfile.ZipFile(target, "w") as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.name != ".mcpbignore":
                zf.write(path, path.relative_to(folder).as_posix())
    return target


def test_smoke_checkout_passes_on_a_bundle_zipped_from_the_stage(build_mcpb, staged, tmp_path):
    """`pack` adds only the MCPB CLI's validation; the zip layout is the staged folder's."""
    bundle = _zip(staged, tmp_path / "test.mcpb")
    result = build_mcpb.smoke(bundle, "checkout", None, 0)
    assert result["tools"] == len(TOOLS)
    assert result["server"] == f"{PRODUCT['name']} {PRODUCT['version']}"


def test_smoke_rejects_a_manifest_whose_tools_differ(build_mcpb, staged, tmp_path):
    data = _manifest(staged)
    data["tools"] = data["tools"][1:]
    (staged / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    bundle = _zip(staged, tmp_path / "drifted.mcpb")
    with pytest.raises(AssertionError, match="differs from the manifest"):
        build_mcpb.smoke(bundle, "checkout", None, 0)
