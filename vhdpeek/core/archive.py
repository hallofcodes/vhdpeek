"""
Tree walking and naming shared by every download surface.

The CLI and the GUI both turn a remote folder into a zip archive. The walk
itself — order, empty dirs, link handling — lives here so the two cannot
drift apart; each surface keeps its own streaming loop, because one reports
to stderr and the other to a progress bar.
"""

from __future__ import annotations

import os
import tempfile
import time
import zipfile
from contextlib import contextmanager
from typing import Callable, Iterator, List, Optional, Tuple

from .volume import Entry

#: (kind, archive name, remote path, size, mtime); kind is "file" or "dir".
WalkItem = Tuple[str, str, str, int, object]

#: Called with a left-out remote path and why ("dangling" or "directory").
SkipFn = Callable[[str, str], None]


def safe_name(name: str, fallback: str) -> str:
    """A single path component that cannot escape its directory."""
    cleaned = name.replace("/", "_").replace("\\", "_").strip()
    if cleaned in ("", ".", ".."):
        return fallback
    return cleaned


def walk_tree(reader, root: Entry,
              on_skip: Optional[SkipFn] = None) -> Iterator[WalkItem]:
    """
    Every file and empty dir under `root`, in stable sorted order.

    Sizes come from `stat`, which follows links to their target. A link with
    no target ("dangling") and a link to a directory ("directory") are
    reported through `on_skip` and left out: the first has no bytes, and
    following the second could loop forever.
    """
    prefix = root.path.rstrip("/")
    stack: List[str] = [root.path]
    while stack:
        current = stack.pop()
        try:
            entries = reader.list_dir(current)
        except Exception as exc:
            raise OSError(f"cannot list {current}: {exc}") from None
        entries.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        if not entries and current != root.path:
            rel = current[len(prefix):].lstrip("/")
            yield ("dir", rel + "/", current, 0, None)
        for item in entries:
            if item.is_dir:
                stack.append(item.path)
                continue
            target = reader.stat(item.path)
            if target is None or target.is_dir:
                if on_skip is not None:
                    reason = "dangling" if target is None else "directory"
                    on_skip(item.path, reason)
                continue
            rel = item.path[len(prefix):].lstrip("/")
            yield ("file", rel, item.path, target.size, target.mtime)


def zip_time(mtime: object) -> Tuple[int, int, int, int, int, int]:
    """A zip-safe timestamp; archives cannot predate 1980."""
    try:
        stamp = time.gmtime(int(mtime))  # type: ignore[arg-type]
        if stamp.tm_year >= 1980:
            return stamp[:6]
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return (1980, 1, 1, 0, 0, 0)


def zip_member(arcname: str, mtime: object, is_dir: bool) -> zipfile.ZipInfo:
    """An archive member with sane timestamps and unix permission bits."""
    member = zipfile.ZipInfo(arcname, zip_time(mtime))
    if is_dir:
        member.external_attr = 0o40755 << 16
    else:
        member.compress_type = zipfile.ZIP_DEFLATED
        member.external_attr = 0o100644 << 16
    return member


@contextmanager
def staged_write(destination: str) -> Iterator[str]:
    """
    Write `destination` atomically: yield a temp sibling, rename on success.

    A failure or a cancel removes the temp file, so the final name never
    points at partial bytes.
    """
    directory = os.path.dirname(os.path.abspath(destination))
    os.makedirs(directory, exist_ok=True)
    handle_no, tmp = tempfile.mkstemp(prefix=".vhdpeek-", suffix=".part",
                                      dir=directory)
    os.close(handle_no)
    try:
        yield tmp
        os.replace(tmp, destination)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
