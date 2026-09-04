"""carrel desk — the flagship Textual TUI.

Zero business logic: every action delegates to the same plain library
functions the CLI commands use (`inspect_file`, `convert_file`, `ocr_file`,
`thumb_file`, `pack_paths`, `DeskDB`, `extract_text`) and runs them in
thread workers so the event loop never blocks. Outputs land in
`<root>/carrel-out/`. Errors surface as toasts — the app never crashes on a
failed action.

Theme lives in styles.tcss; the palette is a variable block at the top so
Phase 6 branding is a variable swap.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from carrel._product import PRODUCT
from carrel.commands.convert import convert_file, supported_targets
from carrel.commands.inspect import inspect_file
from carrel.commands.ocr import ocr_file
from carrel.commands.pack import pack_paths
from carrel.commands.thumb import thumb_file
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect
from carrel.core.output import CarrelError
from carrel.core.textextract import extract_text

PREVIEW_LINES = 200
THUMB_SIZE = 256
PALETTE_COLORS = 6
#: Convert targets the TUI offers (the CLI supports more; these are the
#: one-keypress useful ones per the spec) — filtered per source type.
CONVERT_TARGETS = ("pdf", "txt", "md", "html", "png")
OCR_SOURCES = (FileType.PDF, FileType.JPG, FileType.PNG)
THUMB_SOURCES = (FileType.PDF, FileType.PNG, FileType.JPG, FileType.ICO, FileType.HTML)

ACCENT = "#E8A13D"  # keep in sync with $carrel-accent in styles.tcss
MUTED = "#9A8F7C"  # keep in sync with $carrel-muted in styles.tcss


class FilteredDirectoryTree(DirectoryTree):
    """DirectoryTree limited to non-hidden directories + supported file types."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        keep: list[Path] = []
        for path in paths:
            if path.name.startswith("."):
                continue
            try:
                is_dir = path.is_dir()
            except OSError:
                continue
            if is_dir or detect(path) is not FileType.UNKNOWN:
                keep.append(path)
        return keep


class TextPrompt(ModalScreen[str | None]):
    """One-line modal input; dismisses with the text, or None on escape."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-box"):
            yield Label(self._title, id="prompt-title")
            yield Input(placeholder=self._placeholder, id="prompt-input")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    @on(Input.Submitted, "#prompt-input")
    def _submit(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DeskApp(App[None]):
    """Three panes (tree · inspector · actions) plus a bottom search bar."""

    TITLE = f"{PRODUCT['name']} desk"
    CSS_PATH = "styles.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("/", "focus_search", "Search"),
        Binding("t", "tag_prompt", "Tag"),
        Binding("n", "note_prompt", "Note"),
        Binding("escape", "hide_results", "Hide results", show=False),
    ]

    def __init__(self, root: Path | str = ".") -> None:
        super().__init__()
        self.root_path = Path(root).resolve()
        self.selected: Path | None = self.root_path
        self.selected_is_dir = True
        self.inspected_path: Path | None = None
        self._result_paths: list[str] = []

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield FilteredDirectoryTree(self.root_path, id="tree")
            with VerticalScroll(id="inspector"):
                yield Static(Text("Select a file to inspect.", style=MUTED), id="meta")
                yield Static("", id="preview")
                yield Static("", id="annotations")
            with Vertical(id="actions-pane"):
                yield Label("Actions", id="actions-title")
                yield OptionList(id="actions")
        with Vertical(id="search-bar"):
            yield OptionList(id="results")
            yield Input(placeholder="Search the desk index  (press / to focus)", id="search")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tree", FilteredDirectoryTree).focus()
        self._build_actions()

    # -- selection -------------------------------------------------------------

    @on(DirectoryTree.FileSelected)
    def _on_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        self.show_file(Path(event.path))

    @on(DirectoryTree.DirectorySelected)
    def _on_dir_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        event.stop()
        self.show_dir(Path(event.path))

    def show_file(self, path: Path) -> None:
        """Select `path` and (lazily, off the event loop) populate the inspector."""
        self.selected = path
        self.selected_is_dir = False
        self._build_actions()
        self.query_one("#meta", Static).update(Text(f"Inspecting {path.name} …", style=MUTED))
        self._load_inspector(path)

    def show_dir(self, path: Path) -> None:
        self.selected = path
        self.selected_is_dir = True
        self.inspected_path = None
        self._build_actions()
        meta = Text()
        meta.append(f"{path.name or path}/", style=f"bold {ACCENT}")
        meta.append(
            "\n\ndirectory — Pack bundles it into one LLM-ready document (see Actions).",
            style=MUTED,
        )
        self.query_one("#meta", Static).update(meta)
        self.query_one("#preview", Static).update("")
        self.query_one("#annotations", Static).update("")

    # -- inspector (worker) ------------------------------------------------------

    @work(thread=True, exclusive=True, group="inspector")
    def _load_inspector(self, path: Path) -> None:
        try:
            info = inspect_file(path)
        except CarrelError as e:
            self.call_from_thread(
                self._set_inspector, path, Text(f"error: {e}", style="red"), Text(""), Text("")
            )
            return
        except Exception as e:  # noqa: BLE001 — inspector degrades, never crashes
            self.call_from_thread(
                self._set_inspector,
                path,
                Text(f"unexpected error: {e}", style="red"),
                Text(""),
                Text(""),
            )
            return
        meta = self._meta_text(info)
        preview = self._preview_text(path, FileType(info["type"]))
        annotations = self._annotations_text(path)
        self.call_from_thread(self._set_inspector, path, meta, preview, annotations)

    def _set_inspector(self, path: Path, meta: Text, preview: Text, annotations: Text) -> None:
        if self.selected != path:  # stale worker: selection moved on
            return
        self.inspected_path = path
        self.query_one("#meta", Static).update(meta)
        self.query_one("#preview", Static).update(preview)
        self.query_one("#annotations", Static).update(annotations)

    @staticmethod
    def _meta_text(info: dict) -> Text:
        text = Text()
        text.append(info["name"], style=f"bold {ACCENT}")
        text.append("\n")
        for key in ("path", "type", "mime", "size", "mtime", "sha256"):
            text.append(f"\n{key:>10}  ", style=MUTED)
            text.append(str(info.get(key)))
        detail = info.get("detail") or {}
        if detail:
            text.append("\n\ndetail", style="bold")
            for key, value in detail.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                text.append(f"\n{key:>14}  ", style=MUTED)
                text.append(str(value))
        return text

    def _preview_text(self, path: Path, ftype: FileType) -> Text:
        header = Text(f"── preview {'─' * 30}\n", style=MUTED)
        if ftype.is_image:
            return header + self._image_preview(path)
        try:
            content = extract_text(path)
        except CarrelError as e:
            return header + Text(f"(no preview: {e})", style=MUTED)
        except Exception as e:  # noqa: BLE001
            return header + Text(f"(no preview: {e})", style=MUTED)
        lines = content.splitlines()
        body = Text("\n".join(lines[:PREVIEW_LINES]) or "(empty)")
        if len(lines) > PREVIEW_LINES:
            body.append(f"\n… (+{len(lines) - PREVIEW_LINES} more lines)", style=MUTED)
        return header + body

    @staticmethod
    def _image_preview(path: Path) -> Text:
        """Placeholder image preview: dimensions + palette swatches."""
        try:
            from PIL import Image

            with Image.open(path) as im:
                im.load()
                width, height = im.size
                small = im.convert("RGB").resize((64, 64))
            palette_img = small.quantize(colors=PALETTE_COLORS)
            raw = (palette_img.getpalette() or [])[: PALETTE_COLORS * 3]
        except Exception as e:  # noqa: BLE001
            return Text(f"(no preview: {e})", style=MUTED)
        text = Text(f"{width} x {height} px\n\n")
        text.append("palette  ", style=MUTED)
        for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3], strict=False):
            text.append("    ", style=f"on #{r:02x}{g:02x}{b:02x}")
            text.append(" ")
        return text

    def _annotations_text(self, path: Path) -> Text:
        header = Text(f"── tags & notes {'─' * 25}\n", style=MUTED)
        if not DeskDB.exists(self.root_path):
            return header + Text("no desk index yet — run the 'Index root' action", style=MUTED)
        try:
            with DeskDB(self.root_path) as db:
                tags = db.tags_of(path)
                notes = db.notes_of(path)
        except Exception as e:  # noqa: BLE001
            return header + Text(f"(db error: {e})", style=MUTED)
        text = header
        text.append("tags   ", style="bold")
        text.append(", ".join(tags) if tags else "(none)")
        text.append("\nnotes  ", style="bold")
        if not notes:
            text.append("(none)")
        for row in notes:
            stamp = datetime.fromtimestamp(row["created"]).strftime("%Y-%m-%d %H:%M")
            text.append(f"\n  • {row['body']}  ")
            text.append(f"({stamp})", style=MUTED)
        return text

    # -- actions pane -------------------------------------------------------------

    def _build_actions(self) -> None:
        options: list[Option] = []
        sel = self.selected
        if sel is not None and not self.selected_is_dir:
            ftype = detect(sel)
            for target in CONVERT_TARGETS:
                if target in supported_targets(ftype):
                    options.append(Option(f"Convert → {target}", id=f"convert:{target}"))
            if ftype in OCR_SOURCES:
                options.append(Option("OCR → txt", id="ocr"))
            if ftype in THUMB_SOURCES:
                options.append(Option("Thumbnail", id="thumb"))
            options.append(Option("Tag…", id="tag"))
            options.append(Option("Note…", id="note"))
        if sel is not None and self.selected_is_dir:
            options.append(Option("Pack directory", id="pack"))
        options.append(Option("Index root", id="index"))
        actions = self.query_one("#actions", OptionList)
        actions.clear_options()
        actions.add_options(options)

    @on(OptionList.OptionSelected, "#actions")
    def _on_action_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id:
            self.run_file_action(event.option_id)

    def run_file_action(self, action_id: str) -> None:
        """Dispatch one action by id; all real work runs in a thread worker."""
        sel = self.selected
        out_dir = self.root_path / f"{PRODUCT['cli']}-out"

        if action_id == "index":
            self._run_action("Index", self._index_root)
            return
        if action_id == "tag":
            self.action_tag_prompt()
            return
        if action_id == "note":
            self.action_note_prompt()
            return
        if sel is None:
            self.notify("Select a file or directory first.", severity="warning")
            return

        if action_id.startswith("convert:"):
            target = action_id.split(":", 1)[1]
            dest = out_dir / f"{sel.stem}.{target}"

            def job(src: Path = sel, dest: Path = dest) -> str:
                record = convert_file(src, dest, force=True)
                return f"wrote {record['dest']}"

            self._run_action(f"Convert → {target}", job)
        elif action_id == "ocr":
            dest = out_dir / f"{sel.stem}.ocr.txt"

            def job(src: Path = sel, dest: Path = dest) -> str:
                record = ocr_file(src, dest, to="txt")
                return f"wrote {record['dest']} ({record['chars']} chars)"

            self._run_action("OCR", job)
        elif action_id == "thumb":

            def job(src: Path = sel, dest: Path = out_dir) -> str:
                record = thumb_file(src, dest, THUMB_SIZE, "png")
                return f"wrote {record['thumb']} ({record['w']}x{record['h']})"

            self._run_action("Thumbnail", job)
        elif action_id == "pack":
            dest = out_dir / f"{sel.name or 'root'}.pack.md"

            def job(src: Path = sel, dest: Path = dest) -> str:
                result = pack_paths([src], fmt="md")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(result.document)
                return (
                    f"wrote {dest} ({result.meta['files_included']} files, "
                    f"~{result.meta['tokens_est']} tokens_est)"
                )

            self._run_action("Pack", job)
        else:
            self.notify(f"unknown action: {action_id}", severity="warning")

    @work(thread=True, group="action")
    def _run_action(self, label: str, job: Callable[[], str], refresh: bool = False) -> None:
        try:
            message = job()
        except CarrelError as e:
            self.call_from_thread(
                self.notify, str(e), title=f"{label} failed", severity="error", timeout=10
            )
        except Exception as e:  # noqa: BLE001 — actions toast, never crash
            self.call_from_thread(
                self.notify,
                f"unexpected error: {e}",
                title=f"{label} failed",
                severity="error",
                timeout=10,
            )
        else:
            self.call_from_thread(self.notify, message, title=label, timeout=6)
            if refresh and self.selected is not None and not self.selected_is_dir:
                self.call_from_thread(self._load_inspector, self.selected)

    def _index_root(self) -> str:
        """(Re)index the desk root — same walk/skip rules as `carrel index`."""
        from carrel.commands.index import _walk  # the command's own walker

        indexed = unchanged = errors = 0
        with DeskDB(self.root_path) as db:
            for path in _walk(self.root_path):
                ftype = detect(path)
                if ftype is FileType.UNKNOWN:
                    continue
                if db.is_fresh(path):
                    unchanged += 1
                    continue
                try:
                    text = extract_text(path)
                except CarrelError:
                    errors += 1
                    continue
                fid = db.upsert_file(path, ftype=ftype.value)
                db.set_content(fid, path, text)
                indexed += 1
        return f"indexed {indexed}, unchanged {unchanged}, errors {errors}"

    # -- tag / note prompts ----------------------------------------------------

    def action_tag_prompt(self) -> None:
        sel = self.selected
        if sel is None or self.selected_is_dir:
            self.notify("Select a file to tag.", severity="warning")
            return

        def done(value: str | None) -> None:
            if not value:
                return
            tags = [t.strip() for t in value.split(",") if t.strip()]

            def job(path: Path = sel) -> str:
                with DeskDB(self.root_path) as db:
                    db.add_tags(path, tags)
                return f"tagged {path.name}: {', '.join(tags)}"

            self._run_action("Tag", job, refresh=True)

        self.push_screen(TextPrompt(f"Tag {sel.name}", "comma-separated tags"), done)

    def action_note_prompt(self) -> None:
        sel = self.selected
        if sel is None or self.selected_is_dir:
            self.notify("Select a file to annotate.", severity="warning")
            return

        def done(value: str | None) -> None:
            if not value:
                return

            def job(path: Path = sel) -> str:
                with DeskDB(self.root_path) as db:
                    db.add_note(path, value)
                return f"noted {path.name}"

            self._run_action("Note", job, refresh=True)

        self.push_screen(TextPrompt(f"Note on {sel.name}", "note text"), done)

    # -- search ------------------------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_hide_results(self) -> None:
        results = self.query_one("#results", OptionList)
        if results.display:
            results.display = False
            self.query_one("#tree", FilteredDirectoryTree).focus()

    @on(Input.Submitted, "#search")
    def _on_search_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        query = event.value.strip()
        if not query:
            self._show_results([])
            return
        self._do_search(query)

    @work(thread=True, exclusive=True, group="search")
    def _do_search(self, query: str) -> None:
        if not DeskDB.exists(self.root_path):
            self.call_from_thread(
                self.notify,
                "No desk index yet — run the 'Index root' action first.",
                severity="warning",
            )
            return
        try:
            with DeskDB(self.root_path) as db:
                rows = db.fts_search(query, limit=20)
        except Exception as e:  # noqa: BLE001 — e.g. FTS5 syntax errors
            self.call_from_thread(self.notify, f"search failed: {e}", severity="error")
            return
        hits = [(row["path"], row["snip"]) for row in rows]
        self.call_from_thread(self._show_results, hits)
        if not hits:
            self.call_from_thread(self.notify, f"no hits for {query!r}", severity="warning")

    def _show_results(self, hits: list[tuple[str, str]]) -> None:
        results = self.query_one("#results", OptionList)
        results.clear_options()
        self._result_paths = [path for path, _ in hits]
        for path, snip in hits:
            prompt = Text()
            prompt.append(path, style=f"bold {ACCENT}")
            prompt.append("  " + " ".join(snip.split()), style=MUTED)
            results.add_option(Option(prompt))
        results.display = bool(hits)
        if hits:
            results.highlighted = 0
            results.focus()

    @on(OptionList.OptionSelected, "#results")
    def _on_result_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if not (0 <= event.option_index < len(self._result_paths)):
            return
        path = (self.root_path / self._result_paths[event.option_index]).resolve()
        self.action_hide_results()
        self.show_file(path)
        self.run_worker(self._reveal(path), group="reveal", exit_on_error=False)

    async def _reveal(self, path: Path) -> None:
        """Best-effort: expand the tree down to `path` and move the cursor."""
        tree = self.query_one("#tree", FilteredDirectoryTree)
        try:
            rel = path.relative_to(self.root_path)
        except ValueError:
            return
        node = tree.root
        for part in rel.parts:
            if not node.is_expanded:
                node.expand()
            child = None
            for _ in range(100):  # directory contents load asynchronously
                child = next(
                    (
                        c
                        for c in node.children
                        if c.data is not None and Path(c.data.path).name == part
                    ),
                    None,
                )
                if child is not None:
                    break
                await asyncio.sleep(0.02)
            if child is None:
                return
            node = child
        tree.move_cursor(node)
