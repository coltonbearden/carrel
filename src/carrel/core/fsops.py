"""File moves that keep the desk in step.

`organize --apply`, `rename --apply` and `intake --apply` all move files. A move
must (1) never overwrite (`uncollide`), (2) work across filesystems, and (3)
carry the desk row — tags, notes, fields, index text — with the file when a
desk exists under `desk_root`. Before v0.4.0 a move orphaned that row.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path


def uncollide(dest: Path, taken: Iterable[Path] = ()) -> Path:
    """First non-existing, not-yet-planned variant: name.ext, name-1.ext, …"""
    planned = set(taken)
    candidate, n = dest, 0
    while candidate.exists() or candidate in planned:
        n += 1
        candidate = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
    return candidate


def move_file(src: Path, dest: Path, *, desk_root: Path | None = None) -> Path:
    """Move `src` to `dest` (parents created); the desk row follows when a desk exists.

    `os.replace` first (atomic on one filesystem), `shutil.move` across
    filesystems. Never overwrites: callers pass an `uncollide`d destination.
    """
    from carrel.core.db import DeskDB

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite {dest}")
    try:
        os.replace(src, dest)
    except OSError:
        shutil.move(str(src), str(dest))
    if desk_root is not None and DeskDB.exists(desk_root):
        with DeskDB(desk_root) as db:
            db.rename_path(src, dest)
    return dest
