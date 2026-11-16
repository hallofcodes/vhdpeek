"""Copy-out: a single file, a folder tree, and a folder inside a mounted ISO."""

from __future__ import annotations

import zipfile

import pytest

pytest.importorskip("tkinter", reason="GUI tests need Tk")

from tests.gui_support import (SAMPLE, child, expand, listed, node,
                               open_and_wait, pump, wait_idle)
from vhdpeek.gui import make_iid


class TestCopyOut:
    def test_copy_out_file(self, app, gui_images, tmp_path, monkeypatch):
        target = tmp_path / "saved.txt"
        monkeypatch.setattr("vhdpeek.gui.copy.filedialog.asksaveasfilename",
                            lambda **_kwargs: str(target))

        open_and_wait(app, gui_images["ext4"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        readme = child(app, root_iid, "readme.txt")

        app.tree.selection_set(readme)
        app.tree.focus(readme)
        app._node_selected(None)
        app.copy_out()
        wait_idle(app)
        pump(app, lambda: target.is_file() and target.stat().st_size > 0)
        assert target.read_bytes() == SAMPLE["readme.txt"]

    def test_copy_out_folder_recursively(self, app, gui_images, tmp_path,
                                         monkeypatch):
        monkeypatch.setattr("vhdpeek.gui.copy.filedialog.askdirectory",
                            lambda **_kwargs: str(tmp_path))

        open_and_wait(app, gui_images["ext4"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        data = child(app, root_iid, "data")

        app.tree.selection_set(data)
        app.tree.focus(data)
        app._node_selected(None)
        app.copy_out()
        wait_idle(app)
        pump(app, lambda: (tmp_path / "data" / "sub" / "note.txt").is_file())

        assert (tmp_path / "data" / "blob.bin").read_bytes() == \
            SAMPLE["data/blob.bin"]
        assert (tmp_path / "data" / "sub" / "note.txt").read_bytes() == \
            SAMPLE["data/sub/note.txt"]
        assert "Copied 2 file(s)" in app.status_label.cget("text")

    def test_copy_out_nested_folder_from_iso(self, app, gui_images, tmp_path,
                                             monkeypatch):
        monkeypatch.setattr("vhdpeek.gui.copy.filedialog.askdirectory",
                            lambda **_kwargs: str(tmp_path))
        open_and_wait(app, gui_images["iso_inside"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        casper = child(app, root_iid, "casper")
        expand(app, casper)
        iso_node = child(app, casper, "tiny.iso")
        expand(app, iso_node)

        docs = child(app, iso_node, "docs")
        app.tree.selection_set(docs)
        app.tree.focus(docs)
        app._node_selected(None)
        app.copy_out()
        wait_idle(app)
        pump(app, lambda: (tmp_path / "docs" / "manual.txt").is_file())
        assert (tmp_path / "docs" / "manual.txt").read_bytes() == \
            SAMPLE["docs/manual.txt"]


class TestSaveZip:
    def test_save_zip_folder(self, app, gui_images, tmp_path, monkeypatch):
        target = tmp_path / "data.zip"
        monkeypatch.setattr("vhdpeek.gui.copy.filedialog.asksaveasfilename",
                            lambda **_kwargs: str(target))

        open_and_wait(app, gui_images["ext4"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        data = child(app, root_iid, "data")

        app.tree.selection_set(data)
        app.tree.focus(data)
        app._node_selected(None)
        app.save_zip()
        wait_idle(app)
        pump(app, lambda: target.is_file())

        with zipfile.ZipFile(target) as archive:
            assert archive.read("blob.bin") == SAMPLE["data/blob.bin"]
            assert archive.read("sub/note.txt") == SAMPLE["data/sub/note.txt"]
        assert "Saved" in app.status_label.cget("text")

    def test_save_zip_file(self, app, gui_images, tmp_path, monkeypatch):
        target = tmp_path / "readme.zip"
        monkeypatch.setattr("vhdpeek.gui.copy.filedialog.asksaveasfilename",
                            lambda **_kwargs: str(target))

        open_and_wait(app, gui_images["ext4"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        readme = child(app, root_iid, "readme.txt")

        app.tree.selection_set(readme)
        app.tree.focus(readme)
        app._node_selected(None)
        app.save_zip()
        wait_idle(app)
        pump(app, lambda: target.is_file())

        with zipfile.ZipFile(target) as archive:
            assert archive.namelist() == ["readme.txt"]
            assert archive.read("readme.txt") == SAMPLE["readme.txt"]

    def test_save_zip_nested_folder_from_iso(self, app, gui_images, tmp_path,
                                             monkeypatch):
        target = tmp_path / "docs.zip"
        monkeypatch.setattr("vhdpeek.gui.copy.filedialog.asksaveasfilename",
                            lambda **_kwargs: str(target))
        open_and_wait(app, gui_images["iso_inside"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        casper = child(app, root_iid, "casper")
        expand(app, casper)
        iso_node = child(app, casper, "tiny.iso")
        expand(app, iso_node)

        docs = child(app, iso_node, "docs")
        app.tree.selection_set(docs)
        app.tree.focus(docs)
        app._node_selected(None)
        app.save_zip()
        wait_idle(app)
        pump(app, lambda: target.is_file())

        with zipfile.ZipFile(target) as archive:
            assert archive.read("manual.txt") == SAMPLE["docs/manual.txt"]

    def test_save_zip_needs_a_selection(self, app, gui_images):
        open_and_wait(app, gui_images["ext4"])
        app.save_zip()
        assert "Select a file or folder" in app.status_label.cget("text")

    def test_save_zip_cancelled_dialog_saves_nothing(self, app, gui_images,
                                                     tmp_path, monkeypatch):
        monkeypatch.setattr("vhdpeek.gui.copy.filedialog.asksaveasfilename",
                            lambda **_kwargs: "")
        open_and_wait(app, gui_images["ext4"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        readme = child(app, root_iid, "readme.txt")

        app.tree.selection_set(readme)
        app.tree.focus(readme)
        app._node_selected(None)
        app.save_zip()
        wait_idle(app)
        assert list(tmp_path.iterdir()) == []
