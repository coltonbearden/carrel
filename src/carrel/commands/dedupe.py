"""carrel dedupe — find (and optionally delete) duplicate files.

Exact mode groups by BLAKE2b content hash (with a size prefilter so only
same-sized files are hashed). --near switches to perceptual matching for
images only: a custom 64-bit dHash (9x8 grayscale resize, horizontal
gradient bits) clustered at Hamming distance <= 8.

Deletion is double-gated: nothing is removed unless BOTH --delete
newest|oldest AND --apply are given. The kept member is never deleted.
"""

from __future__ import annotations

import functools
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import click

from carrel.core.db import file_hash
from carrel.core.filetypes import detect
from carrel.core.output import CarrelError, CarrelInputError, emit, fail

NEAR_HAMMING_MAX = 8


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


def _walk(top: Path) -> Iterator[Path]:
    """Files under `top`, skipping hidden entries and symlinked dirs."""
    try:
        children = sorted(top.iterdir(), key=lambda p: p.name)
    except OSError:
        return
    for child in children:
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if not child.is_symlink():
                yield from _walk(child)
        elif child.is_file():
            yield child


# -- perceptual hashing -------------------------------------------------------


def dhash(path: Path) -> int:
    """64-bit difference hash: 9x8 grayscale resize, horizontal gradients."""
    from PIL import Image

    with Image.open(path) as img:
        gray = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = gray.tobytes()  # mode L: one byte per pixel, row-major
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if px[y * 9 + x] > px[y * 9 + x + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _cluster_near(hashes: dict[Path, int]) -> list[list[Path]]:
    """Union-find clusters of paths whose dHashes are within NEAR_HAMMING_MAX."""
    paths = sorted(hashes)
    parent = {p: p for p in paths}

    def find(p: Path) -> Path:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for i, a in enumerate(paths):
        for b in paths[i + 1 :]:
            if hamming(hashes[a], hashes[b]) <= NEAR_HAMMING_MAX:
                parent[find(a)] = find(b)

    clusters: dict[Path, list[Path]] = defaultdict(list)
    for p in paths:
        clusters[find(p)].append(p)
    return [members for members in clusters.values() if len(members) > 1]


# -- grouping -----------------------------------------------------------------


def _exact_groups(files: list[Path]) -> list[tuple[str, list[Path]]]:
    by_size: dict[int, list[Path]] = defaultdict(list)
    for f in files:
        by_size[f.stat().st_size].append(f)
    groups: list[tuple[str, list[Path]]] = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for f in same_size:
            by_hash[file_hash(f)].append(f)
        groups.extend((h, members) for h, members in by_hash.items() if len(members) > 1)
    return groups


def _near_groups(files: list[Path]) -> list[tuple[str, list[Path]]]:
    hashes: dict[Path, int] = {}
    for f in files:
        if not detect(f).is_image:
            continue
        try:
            hashes[f] = dhash(f)
        except Exception as e:  # noqa: BLE001 — unreadable image: warn + skip
            click.echo(f"warning: cannot hash {f}: {e}", err=True)
    return [(f"dhash:{hashes[members[0]]:016x}", members) for members in _cluster_near(hashes)]


def _human_report(reclaimable: int, applied: bool) -> Callable[[list[dict]], None]:
    def _print(groups: list[dict[str, Any]]) -> None:
        if not groups:
            click.echo("no duplicates found.")
            return
        for group in groups:
            click.echo(f"{group['hash']}  ({len(group['files'])} files)")
            for f in group["files"]:
                marker = (
                    "keep " if f == group["kept"] else "DEL  " if f in group["deleted"] else "dup  "
                )
                click.echo(f"  {marker} {f}")
        verb = "reclaimed" if applied else "reclaimable"
        click.echo(
            f"{len(groups)} group(s); {verb}: {reclaimable} bytes"
            + ("" if applied else " (report only — use --delete newest|oldest --apply to remove)")
        )

    return _print


@click.command(name="dedupe")
@click.argument("dirs", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "--near",
    is_flag=True,
    help="Perceptual matching for images (64-bit dHash, Hamming "
    "distance <= 8) instead of exact content hashing. "
    "Non-image files are ignored in this mode.",
)
@click.option(
    "--delete",
    "delete_",
    type=click.Choice(["newest", "oldest"]),
    default=None,
    help="Which duplicates to delete per group (by mtime); the "
    "other end of the range is kept. Requires --apply to "
    "actually remove files.",
)
@click.option(
    "--apply", "apply_", is_flag=True, help="Actually delete (only together with --delete)."
)
@click.pass_context
@_handled
def cmd(
    ctx: click.Context, dirs: tuple[Path, ...], near: bool, delete_: str | None, apply_: bool
) -> None:
    """Report duplicate files under DIRS (recursively; hidden entries skipped).

    Default is report-only. Deletion needs BOTH --delete newest|oldest AND
    --apply; without --apply the deletions are only planned. The kept member
    of each group is never deleted. JSON output is a list of
    {hash, files, kept, deleted}.
    """
    if apply_ and delete_ is None:
        raise click.UsageError("--apply requires --delete newest|oldest")

    files: list[Path] = []
    for d in dirs:
        d = d.resolve()
        if not d.is_dir():
            raise CarrelInputError(f"no such directory: {d}")
        files.extend(_walk(d))

    raw_groups = _near_groups(files) if near else _exact_groups(files)

    result: list[dict[str, Any]] = []
    reclaimable = 0
    for digest, members in raw_groups:
        # oldest first; name tie-breaks so equal mtimes stay deterministic
        ordered = sorted(members, key=lambda p: (p.stat().st_mtime, str(p)))
        kept = ordered[-1] if delete_ == "oldest" else ordered[0]
        doomed = [p for p in ordered if p != kept] if delete_ else []
        reclaimable += (
            sum(p.stat().st_size for p in doomed)
            if doomed
            else sum(p.stat().st_size for p in ordered[1:])
        )
        if apply_:
            for p in doomed:
                p.unlink()
        result.append(
            {
                "hash": digest,
                "files": [str(p) for p in ordered],
                "kept": str(kept),
                "deleted": [str(p) for p in doomed],
            }
        )
    result.sort(key=lambda g: g["files"])

    emit(ctx, result, human=_human_report(reclaimable, applied=apply_))
