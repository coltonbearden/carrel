"""Pilot tests for the carrel desk TUI (headless, no optional binaries).

Driven through textual's App.run_test(). The project has no async pytest
plugin, so each test wraps its scenario in asyncio.run().
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

pytest.importorskip("textual", reason="requires the tui extra: uv sync --extra tui")
from textual.widgets import Input, OptionList, Static

from carrel.cli import cli
from carrel.core.db import DeskDB
from carrel.desk.app import DeskApp, FilteredDirectoryTree

SEARCH_WORD = "quokka"
NOTES_TEXT = f"a quiet {SEARCH_WORD} reads at the reference desk\n"


@pytest.fixture
def desk_root(tmp_path: Path, fixtures: Path) -> Path:
    """A tiny desk: one png fixture + one text file, text pre-indexed."""
    shutil.copy2(fixtures / "sample.png", tmp_path / "sample.png")
    notes = tmp_path / "notes.txt"
    notes.write_text(NOTES_TEXT)
    with DeskDB(tmp_path) as db:
        fid = db.upsert_file(notes, ftype="txt")
        db.set_content(fid, notes, notes.read_text())
    return tmp_path


async def wait_for(pilot, condition, timeout: float = 10.0, what: str = "") -> None:
    """Poll `condition` between pilot pauses; fail loudly on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError(f"timed out waiting for {what or condition}")


def static_text(app: DeskApp, selector: str) -> str:
    return str(app.query_one(selector, Static).content)


def tree_ready(app: DeskApp):
    tree = app.query_one("#tree", FilteredDirectoryTree)
    return lambda: len(tree.root.children) > 0


# ---------------------------------------------------------------------------


def test_desk_help() -> None:
    result = CliRunner().invoke(cli, ["desk", "--help"])
    assert result.exit_code == 0
    assert "desk TUI" in result.output


def test_boot_and_tree_renders(desk_root: Path) -> None:
    async def scenario() -> None:
        app = DeskApp(desk_root)
        async with app.run_test(size=(120, 40)) as pilot:
            # three panes + search bar exist
            assert app.query_one("#inspector")
            assert app.query_one("#actions", OptionList)
            assert app.query_one("#search", Input)
            await wait_for(pilot, tree_ready(app), what="tree children")
            tree = app.query_one("#tree", FilteredDirectoryTree)
            names = {Path(str(child.data.path)).name for child in tree.root.children}
            assert names == {"notes.txt", "sample.png"}  # .carrel is hidden

    asyncio.run(scenario())


def test_selection_populates_inspector(desk_root: Path) -> None:
    async def scenario() -> None:
        app = DeskApp(desk_root)
        async with app.run_test(size=(120, 40)) as pilot:
            await wait_for(pilot, tree_ready(app), what="tree children")
            # cursor: root → first child (notes.txt sorts before sample.png)
            await pilot.press("down", "enter")
            expected = (desk_root / "notes.txt").resolve()
            await wait_for(
                pilot, lambda: app.inspected_path == expected, what="inspector to load notes.txt"
            )
            meta = static_text(app, "#meta")
            assert "notes.txt" in meta
            assert "txt" in meta
            preview = static_text(app, "#preview")
            assert SEARCH_WORD in preview  # first-200-lines text preview
            annotations = static_text(app, "#annotations")
            assert "tags" in annotations  # desk db exists → tags/notes shown

    asyncio.run(scenario())


def test_search_returns_preindexed_hit(desk_root: Path) -> None:
    async def scenario() -> None:
        app = DeskApp(desk_root)
        async with app.run_test(size=(120, 40)) as pilot:
            await wait_for(pilot, tree_ready(app), what="tree children")
            await pilot.press("/")
            assert isinstance(app.focused, Input)
            await pilot.press(*SEARCH_WORD, "enter")
            results = app.query_one("#results", OptionList)
            await wait_for(pilot, lambda: results.option_count > 0, what="search results")
            assert results.display
            assert app._result_paths == ["notes.txt"]
            # results list took focus; enter opens the hit in the inspector
            await pilot.press("enter")
            expected = (desk_root / "notes.txt").resolve()
            await wait_for(
                pilot, lambda: app.inspected_path == expected, what="result to open in inspector"
            )
            assert "notes.txt" in static_text(app, "#meta")

    asyncio.run(scenario())


def test_thumbnail_action_writes_to_carrel_out(desk_root: Path) -> None:
    async def scenario() -> None:
        app = DeskApp(desk_root)
        async with app.run_test(size=(120, 40)) as pilot:
            await wait_for(pilot, tree_ready(app), what="tree children")
            app.show_file(desk_root / "sample.png")
            await wait_for(
                pilot, lambda: app.inspected_path == desk_root / "sample.png", what="png inspector"
            )
            # actions pane offers the per-type actions for a png
            actions = app.query_one("#actions", OptionList)
            ids = [actions.get_option_at_index(i).id for i in range(actions.option_count)]
            assert "thumb" in ids
            assert "ocr" in ids
            assert "convert:pdf" in ids
            assert "convert:txt" not in ids  # invalid target for png
            app.run_file_action("thumb")
            thumb = desk_root / "carrel-out" / "sample.png"
            await wait_for(pilot, thumb.exists, what="thumbnail file")
            await pilot.pause()  # let the completion toast land

        from PIL import Image

        with Image.open(thumb) as im:
            assert max(im.size) <= 256

    asyncio.run(scenario())
