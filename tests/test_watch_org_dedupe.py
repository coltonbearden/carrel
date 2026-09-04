"""Tests for carrel watch / organize / dedupe (spec 08).

The watch integration tests run the command in a background thread with a
threading-based stop (--once / --timeout) and poll for the action's side
effect with a deadline — no blind sleeps. All file activity happens in
tmp_path; fixtures are only ever copied out, never touched in place.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from carrel.cli import cli
from carrel.commands.dedupe import dhash, hamming
from carrel.commands.watch import _due, _render

# ------------------------------------------------------------------ helpers

DEADLINE = 20.0  # generous wall-clock cap for the threaded watch tests


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str, expect: int = 0):
    result = run("--json", *args, expect=expect)
    return json.loads(result.output)


def run_watch_in_thread(args: list[str]):
    """Start `carrel watch` in a thread; returns (thread, result-holder)."""
    holder: dict[str, object] = {}

    def target() -> None:
        holder["result"] = CliRunner().invoke(cli, args)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, holder


def poke_until(trigger: Path, done, deadline: float = DEADLINE) -> None:
    """Repeatedly touch `trigger` until `done()` — retries cover the gap
    between thread start and the watchdog observer actually being armed."""
    end = time.time() + deadline
    while time.time() < end and not done():
        trigger.write_text("poke\n")
        time.sleep(0.15)
    assert done(), f"watch never reacted within {deadline}s"


def finish(thread: threading.Thread, holder: dict, expect: int = 0):
    thread.join(timeout=DEADLINE)
    assert not thread.is_alive(), "watch did not exit (stop event never fired?)"
    result = holder["result"]
    assert result.exit_code == expect, (
        f"exit {result.exit_code}: {result.output}\n{result.stderr}\n{result.exception!r}"
    )
    return result


def stripes_png(path: Path) -> Path:
    """An image perceptually far from the sample-art fixtures (dHash-wise)."""
    img = Image.new("L", (90, 80))
    for x in range(90):
        for y in range(80):
            img.putpixel((x, y), 255 if (x // 10) % 2 == 0 else 0)
    img.save(path)
    return path


# -------------------------------------------------------------------- watch


def test_watch_render_substitutes_and_quotes():
    path = Path("/tmp/some dir/my file.pdf")
    assert _render("do {path}", path) == "do '/tmp/some dir/my file.pdf'"
    assert _render("n={name} d={dir}", path) == "n='my file.pdf' d='/tmp/some dir'"
    assert _render("no placeholders", path) == "no placeholders"


def test_watch_due_coalesces_per_path_within_window():
    a, b = Path("/x/a"), Path("/x/b")
    pending: dict[Path, tuple[str, float]] = {}
    pending[a] = ("created", 100.0)
    pending[a] = ("modified", 100.2)  # same path re-fires: coalesced, timer reset
    pending[b] = ("created", 100.0)
    # at t=100.4 only b's window (0.3s = 300ms) has elapsed
    assert _due(pending, 100.4, 300) == [("created", b)]
    assert list(pending) == [a]
    # a becomes due later, reporting only its latest event type
    assert _due(pending, 100.6, 300) == [("modified", a)]
    assert pending == {}


def test_watch_once_runs_actions_in_order_then_exits(tmp_path: Path):
    watched = tmp_path / "watched"
    watched.mkdir()
    log = tmp_path / "log.txt"
    thread, holder = run_watch_in_thread(
        [
            "watch",
            str(watched),
            "--debounce",
            "50",
            "--once",
            "--timeout",
            str(DEADLINE),
            "--run",
            f"echo one {{path}} >> {log}",
            "--run",
            f"echo two {{name}} >> {log}",
        ]
    )
    poke_until(
        watched / "hello.txt", lambda: log.exists() and len(log.read_text().splitlines()) >= 2
    )
    finish(thread, holder)
    lines = log.read_text().splitlines()
    assert len(lines) == 2  # --once: exactly one coalesced action batch
    assert lines[0] == f"one {watched / 'hello.txt'}"
    assert lines[1] == "two hello.txt"


def test_watch_json_lines_output(tmp_path: Path):
    watched = tmp_path / "watched"
    watched.mkdir()
    marker = tmp_path / "marker"
    thread, holder = run_watch_in_thread(
        [
            "watch",
            str(watched),
            "--debounce",
            "50",
            "--once",
            "--timeout",
            str(DEADLINE),
            "--json-lines",
            "--run",
            f"touch {marker}",
        ]
    )
    poke_until(watched / "data.txt", marker.exists)
    result = finish(thread, holder)
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines, "expected at least one JSON log line on stdout"
    for line in lines:
        record = json.loads(line)
        assert record["rc"] == 0
        assert record["event"] in ("created", "modified")
        assert record["path"] == str(watched / "data.txt")
        assert str(marker) in record["cmd"]


def test_watch_glob_filters_events(tmp_path: Path):
    watched = tmp_path / "watched"
    watched.mkdir()
    log = tmp_path / "log.txt"
    thread, holder = run_watch_in_thread(
        [
            "watch",
            str(watched),
            "--glob",
            "*.txt",
            "--debounce",
            "30",
            "--once",
            "--timeout",
            str(DEADLINE),
            "--run",
            f"echo {{name}} >> {log}",
        ]
    )
    # touch BOTH names each round: if the glob leaked, skip.md would win a
    # race at least sometimes and show up in the log
    end = time.time() + DEADLINE
    while time.time() < end and not log.exists():
        (watched / "skip.md").write_text("nope")
        (watched / "take.txt").write_text("yes")
        time.sleep(0.15)
    assert log.exists(), "watch never reacted to the .txt file"
    finish(thread, holder)
    names = set(log.read_text().split())
    assert names == {"take.txt"}


def test_watch_timeout_exits_cleanly_without_events(tmp_path: Path):
    watched = tmp_path / "watched"
    watched.mkdir()
    start = time.monotonic()
    result = run("watch", str(watched), "--timeout", "0.4", "--run", "echo never")
    assert time.monotonic() - start < DEADLINE
    assert "echo never" not in result.output  # no action ever fired


def test_watch_missing_dir_exits_4(tmp_path: Path):
    run("watch", str(tmp_path / "nope"), "--run", "true", expect=4)


def test_watch_bad_event_name_is_usage_error(tmp_path: Path):
    run("watch", str(tmp_path), "--on", "created,bogus", "--run", "true", expect=2)


def test_watch_requires_run(tmp_path: Path):
    run("watch", str(tmp_path), expect=2)


# ----------------------------------------------------------------- organize


@pytest.fixture
def messy(tmp_path: Path, tmp_copy) -> Path:
    """A directory with one file per type category + one unsupported file."""
    tmp_copy("b.pdf")
    tmp_copy("sample.jpg")
    tmp_copy("sample.json")
    tmp_copy("sample.md")
    tmp_copy("sample.txt")
    (tmp_path / "unsupported.xyz").write_text("???")
    return tmp_path


def plan_of(data: list[dict]) -> dict[str, str | None]:
    return {entry["src"]: entry["dest"] for entry in data}


def test_organize_dry_run_plans_type_layout_and_moves_nothing(messy: Path):
    data = run_json("organize", str(messy))
    dests = plan_of(data)
    assert dests[str(messy / "b.pdf")] == str(messy / "pdf" / "b.pdf")
    assert dests[str(messy / "sample.jpg")] == str(messy / "images" / "sample.jpg")
    assert dests[str(messy / "sample.json")] == str(messy / "data" / "sample.json")
    assert dests[str(messy / "sample.md")] == str(messy / "docs" / "sample.md")
    assert dests[str(messy / "sample.txt")] == str(messy / "docs" / "sample.txt")
    skip = next(e for e in data if e["src"] == str(messy / "unsupported.xyz"))
    assert skip["action"] == "skip" and skip["dest"] is None
    # dry-run: nothing moved, no subdirs created
    assert (messy / "b.pdf").is_file()
    assert not (messy / "pdf").exists()
    assert all(e["action"] in ("move", "skip") for e in data)


def test_organize_apply_moves_files(messy: Path):
    data = run_json("organize", str(messy), "--apply")
    moved = [e for e in data if e["action"] == "moved"]
    assert len(moved) == 5
    for entry in moved:
        assert not Path(entry["src"]).exists()
        assert Path(entry["dest"]).is_file()
    assert (messy / "unsupported.xyz").is_file()  # skips stay put
    # second run over the result: subdirs are untouched (non-recursive)
    again = run_json("organize", str(messy), "--apply")
    assert [e["action"] for e in again] == ["skip"]


def test_organize_never_overwrites_collision_suffix(messy: Path):
    (messy / "pdf").mkdir()
    (messy / "pdf" / "b.pdf").write_bytes(b"%PDF-existing")
    data = run_json("organize", str(messy), "--apply")
    entry = next(e for e in data if e["src"] == str(messy / "b.pdf"))
    assert entry["dest"] == str(messy / "pdf" / "b-1.pdf")
    assert (messy / "pdf" / "b-1.pdf").is_file()
    assert (messy / "pdf" / "b.pdf").read_bytes() == b"%PDF-existing"


def test_organize_by_date_uses_mtime(tmp_path: Path, tmp_copy):
    f = tmp_copy("sample.txt")
    stamp = datetime(2020, 3, 15, 12, 0).timestamp()
    os.utime(f, (stamp, stamp))
    data = run_json("organize", str(tmp_path), "--by", "date")
    assert plan_of(data)[str(f)] == str(tmp_path / "2020" / "03" / "sample.txt")


def test_organize_by_exif_date(tmp_path: Path, tmp_copy):
    jpg = tmp_copy("sample.jpg")  # EXIF DateTimeOriginal 2021:06:15
    png = tmp_copy("sample.png")  # no EXIF -> mtime fallback
    txt = tmp_copy("sample.txt")  # not an image -> skipped
    stamp = datetime(2019, 11, 2).timestamp()
    os.utime(png, (stamp, stamp))
    data = run_json("organize", str(tmp_path), "--by", "exif-date")
    dests = plan_of(data)
    assert dests[str(jpg)] == str(tmp_path / "2021" / "06" / "sample.jpg")
    assert dests[str(png)] == str(tmp_path / "2019" / "11" / "sample.png")
    txt_entry = next(e for e in data if e["src"] == str(txt))
    assert txt_entry["action"] == "skip"


def test_organize_into_override(messy: Path):
    data = run_json("organize", str(messy), "--into", "images=pics")
    dests = plan_of(data)
    assert dests[str(messy / "sample.jpg")] == str(messy / "pics" / "sample.jpg")
    assert dests[str(messy / "b.pdf")] == str(messy / "pdf" / "b.pdf")


def test_organize_into_bad_spec_is_usage_error(messy: Path):
    run("organize", str(messy), "--into", "movies=cinema", expect=2)
    run("organize", str(messy), "--into", "images", expect=2)
    run("organize", str(messy), "--by", "date", "--into", "images=pics", expect=2)


def test_organize_missing_dir_exits_4(tmp_path: Path):
    run("organize", str(tmp_path / "nope"), expect=4)


# ------------------------------------------------------------------- dedupe


@pytest.fixture
def dup_dir(tmp_path: Path, tmp_copy) -> Path:
    """sample.jpg + byte-identical copy (copy is newer) + an unrelated file."""
    original = tmp_copy("sample.jpg")
    copy = tmp_copy("sample-copy.jpg")
    tmp_copy("sample.txt")
    old = datetime(2020, 1, 1).timestamp()
    new = datetime(2023, 1, 1).timestamp()
    os.utime(original, (old, old))
    os.utime(copy, (new, new))
    return tmp_path


def test_dedupe_exact_finds_planted_pair(dup_dir: Path):
    groups = run_json("dedupe", str(dup_dir))
    assert len(groups) == 1
    group = groups[0]
    assert set(group["files"]) == {str(dup_dir / "sample.jpg"), str(dup_dir / "sample-copy.jpg")}
    assert group["kept"] == str(dup_dir / "sample.jpg")  # oldest by default
    assert group["deleted"] == []
    assert len(group["hash"]) == 128  # blake2b hexdigest


def test_dedupe_near_clusters_resized_copy(tmp_path: Path, tmp_copy):
    jpg = tmp_copy("sample.jpg")
    resized = tmp_copy("sample-resized.jpg")  # 75% resize: different bytes
    other = stripes_png(tmp_path / "stripes.png")
    assert hamming(dhash(jpg), dhash(resized)) <= 8  # the premise
    assert hamming(dhash(jpg), dhash(other)) > 8
    # exact mode does NOT pair them
    assert run_json("dedupe", str(tmp_path)) == []
    groups = run_json("dedupe", str(tmp_path), "--near")
    assert len(groups) == 1
    assert set(groups[0]["files"]) == {str(jpg), str(resized)}
    assert groups[0]["hash"].startswith("dhash:")


def test_dedupe_near_ignores_non_images(dup_dir: Path):
    (dup_dir / "a.txt").write_text("same words")
    (dup_dir / "b.txt").write_text("same words")
    groups = run_json("dedupe", str(dup_dir), "--near")
    listed = {f for g in groups for f in g["files"]}
    assert str(dup_dir / "a.txt") not in listed
    assert str(dup_dir / "b.txt") not in listed


def test_dedupe_delete_without_apply_deletes_nothing(dup_dir: Path):
    groups = run_json("dedupe", str(dup_dir), "--delete", "newest")
    assert groups[0]["deleted"] == [str(dup_dir / "sample-copy.jpg")]
    assert (dup_dir / "sample-copy.jpg").is_file()  # plan only — still there
    assert (dup_dir / "sample.jpg").is_file()


def test_dedupe_delete_newest_apply_keeps_oldest(dup_dir: Path):
    groups = run_json("dedupe", str(dup_dir), "--delete", "newest", "--apply")
    assert groups[0]["kept"] == str(dup_dir / "sample.jpg")
    assert groups[0]["deleted"] == [str(dup_dir / "sample-copy.jpg")]
    assert (dup_dir / "sample.jpg").is_file()
    assert not (dup_dir / "sample-copy.jpg").exists()


def test_dedupe_delete_oldest_apply_keeps_newest(dup_dir: Path):
    groups = run_json("dedupe", str(dup_dir), "--delete", "oldest", "--apply")
    assert groups[0]["kept"] == str(dup_dir / "sample-copy.jpg")
    assert not (dup_dir / "sample.jpg").exists()
    assert (dup_dir / "sample-copy.jpg").is_file()


def test_dedupe_apply_without_delete_is_usage_error(dup_dir: Path):
    run("dedupe", str(dup_dir), "--apply", expect=2)


def test_dedupe_human_report_mentions_reclaimable(dup_dir: Path):
    result = run("dedupe", str(dup_dir))
    assert "reclaimable" in result.output
    size = (dup_dir / "sample-copy.jpg").stat().st_size
    assert str(size) in result.output


def test_dedupe_multiple_dirs_and_no_dupes(tmp_path: Path, tmp_copy):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(), b.mkdir()
    tmp_copy("sample.txt", "a/sample.txt")
    tmp_copy("sample.txt", "b/other.txt")
    assert len(run_json("dedupe", str(a), str(b))) == 1  # across dirs
    assert run_json("dedupe", str(a)) == []  # alone: no dupes


def test_dedupe_missing_dir_exits_4(tmp_path: Path):
    run("dedupe", str(tmp_path / "nope"), expect=4)


# --------------------------------------------------------------- plumbing


def test_helps_work():
    watch_help = run("watch", "--help").output
    assert "{path}" in watch_help
    organize_help = run("organize", "--help").output
    for word in ("pdf/", "images/", "data/", "docs/"):
        assert word in organize_help
    dedupe_help = run("dedupe", "--help").output
    assert "--near" in dedupe_help and "--apply" in dedupe_help


def test_json_output_is_single_document(messy: Path):
    result = run("--json", "organize", str(messy))
    json.loads(result.output)
