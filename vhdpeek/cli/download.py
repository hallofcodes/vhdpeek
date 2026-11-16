"""
Download: a file is saved as-is, a folder is saved as a zip archive.

Everything streams in chunks, so a multi-gigabyte file never sits in memory
whole. The destination is written to a temporary file in the same directory
and renamed into place, so an interrupted download never leaves a partial
file behind under the final name.
"""

from __future__ import annotations

import os
import zipfile
from typing import Optional

from ..core.archive import safe_name, staged_write, walk_tree, zip_member
from ..core.volume import Entry, format_size
from .render import info

COPY_CHUNK = 1 << 20


def download(reader, remote_path: str, out: Optional[str] = None,
             overwrite: bool = False, quiet: bool = False) -> str:
    """
    Save `remote_path` locally; return the destination path.

    Files are written byte-exact. Folders become a `.zip` holding the whole
    tree. Raises `FileNotFoundError` for a missing remote path and
    `FileExistsError` when the destination exists without `overwrite`.
    """
    entry = reader.stat(remote_path)
    if entry is None:
        raise FileNotFoundError(remote_path)
    if entry.is_dir:
        dest = _zip_dest(entry, out)
        _check_dest(dest, overwrite)
        return _download_dir(reader, entry, dest, quiet)
    dest = _file_dest(entry, out)
    _check_dest(dest, overwrite)
    return _download_file(reader, entry, dest, quiet)


def _file_dest(entry: Entry, out: Optional[str]) -> str:
    if out is None:
        return safe_name(entry.name, "download")
    if os.path.isdir(out):
        return os.path.join(out, safe_name(entry.name, "download"))
    return out


def _zip_dest(entry: Entry, out: Optional[str]) -> str:
    base = safe_name(entry.name, "root")
    default = base if base.lower().endswith(".zip") else base + ".zip"
    if out is None:
        return default
    if os.path.isdir(out):
        return os.path.join(out, default)
    if out.lower().endswith(".zip"):
        return out
    return out + ".zip"


def _check_dest(dest: str, overwrite: bool) -> None:
    if os.path.lexists(dest) and not overwrite:
        raise FileExistsError(dest)


def _download_file(reader, entry: Entry, dest: str, quiet: bool) -> str:
    read = reader.file_reader(entry.path)
    done = 0
    with staged_write(dest) as tmp:
        with open(tmp, "wb") as handle:
            while done < entry.size:
                chunk = read(done, min(COPY_CHUNK, entry.size - done))
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
    if not quiet:
        info(f"Saved {format_size(done)} to {dest}")
    return dest


def _download_dir(reader, root: Entry, dest: str, quiet: bool) -> str:
    def skipped(path: str, reason: str) -> None:
        info(f"Warning: skipping {path} ({reason} link)")

    count = 0
    total = 0
    with staged_write(dest) as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            items = walk_tree(reader, root, on_skip=skipped)
            for kind, arcname, remote, size, mtime in items:
                if kind == "dir":
                    archive.writestr(zip_member(arcname, mtime, True), b"")
                    continue
                read = reader.file_reader(remote)
                done = 0
                with archive.open(zip_member(arcname, mtime, False),
                                  mode="w") as handle:
                    while done < size:
                        chunk = read(done, min(COPY_CHUNK, size - done))
                        if not chunk:
                            break
                        handle.write(chunk)
                        done += len(chunk)
                count += 1
                total += done
    if not quiet:
        info(f"Saved {count} file(s), {format_size(total)} to {dest}")
    return dest
