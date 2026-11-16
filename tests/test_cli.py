"""The CLI: partition listing, tree, ls, cat, and the ISO/partition switches."""

from __future__ import annotations

import os
import zipfile

import pytest

from vhdpeek.cli import main

from tests.fixtures import fsgen, vhdgen

SAMPLE = {
    "readme.txt": b"Hello from vhdpeek test\nLine 2\n",
    "docs/": b"",
    "docs/manual.txt": b"Manual content\n",
    "data/": b"",
    "data/blob.bin": b"\x00\x01\x02\x03\x04\x05" * 100,
}


@pytest.fixture(scope="module")
def images(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("cli-images")

    iso = fsgen.build_iso(SAMPLE)
    with_iso = dict(SAMPLE)
    with_iso["casper/"] = b""
    with_iso["casper/tiny.iso"] = iso

    two = vhdgen.assemble_disk_multi([
        (2048, fsgen.build_fat32(SAMPLE), 0x0C, None, "FAT32"),
        (10240, fsgen.build_ext4(SAMPLE), 0x83, None, "Linux"),
    ], scheme="mbr")

    paths = {
        "ext4": out / "ext4.vhd",
        "fat32": out / "fat32.vhd",
        "iso_inside": out / "iso_inside.vhd",
        "two": out / "two.vhd",
    }
    paths["ext4"].write_bytes(vhdgen.wrap_fixed_vhd(
        vhdgen.assemble_disk(fsgen.build_ext4(SAMPLE), "mbr", 1)))
    paths["fat32"].write_bytes(vhdgen.wrap_fixed_vhd(
        vhdgen.assemble_disk(fsgen.build_fat32(SAMPLE), "mbr", 1)))
    paths["iso_inside"].write_bytes(vhdgen.wrap_fixed_vhd(
        vhdgen.assemble_disk(fsgen.build_ext4(with_iso), "mbr", 1)))
    paths["two"].write_bytes(vhdgen.wrap_fixed_vhd(two))
    return {name: str(path) for name, path in paths.items()}


def run(capsys, *argv) -> tuple:
    """Run the CLI; return (exit code, stdout text, stderr text)."""
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestParts:
    def test_lists_partitions_and_stops(self, capsys, images):
        code, out, err = run(capsys, images["two"], "--parts")
        assert code == 0
        assert "=== Partitions ===" in err
        assert "FAT32" in err and "Linux" in err
        assert out == ""            # nothing on stdout

    def test_single_partition_image(self, capsys, images):
        code, _out, err = run(capsys, images["ext4"], "--parts")
        assert code == 0
        assert "[0]" in err

    def test_reports_the_container_format(self, capsys, images):
        _code, _out, err = run(capsys, images["ext4"], "--parts")
        assert "FIXED" in err


class TestTree:
    def test_default_action_prints_a_tree(self, capsys, images):
        code, out, err = run(capsys, images["ext4"])
        assert code == 0
        assert "readme.txt" in out
        assert "docs" in out
        assert "+-- " in out or "|-- " in out
        assert "Partition 0: ext" in err

    def test_depth_limit_is_respected(self, capsys, images):
        _code, out, _err = run(capsys, images["ext4"], "--max-depth", "1")
        assert "readme.txt" in out
        assert "manual.txt" not in out

    def test_fs_override_skips_detection(self, capsys, images):
        code, out, _err = run(capsys, images["ext4"], "--fs", "ext")
        assert code == 0
        assert "readme.txt" in out


class TestListing:
    def test_ls_root(self, capsys, images):
        code, out, _err = run(capsys, images["ext4"], "--ls", "")
        assert code == 0
        names = {line.split()[-1] for line in out.splitlines() if line}
        assert {"readme.txt", "docs", "data"} <= names

    def test_ls_marks_directories(self, capsys, images):
        _code, out, _err = run(capsys, images["ext4"], "--ls", "")
        lines = {line.split()[-1]: line for line in out.splitlines() if line}
        assert lines["docs"].startswith("d")
        assert lines["readme.txt"].startswith("-")

    def test_ls_subdirectory(self, capsys, images):
        code, out, _err = run(capsys, images["ext4"], "--ls", "/docs")
        assert code == 0
        assert "manual.txt" in out


class TestCat:
    def test_streams_exact_bytes(self, capsys, images):
        code = main([images["ext4"], "--cat", "/readme.txt"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.encode() == SAMPLE["readme.txt"]

    def test_diagnostics_do_not_contaminate_stdout(self, capsys, images):
        main([images["ext4"], "--cat", "/readme.txt"])
        captured = capsys.readouterr()
        assert captured.err            # diagnostics present
        assert "Source:" not in captured.out

    def test_binary_file_is_byte_exact(self, capsys, images):
        code = main([images["ext4"], "--cat", "/data/blob.bin"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.encode() == SAMPLE["data/blob.bin"]

    def test_missing_file_raises(self, capsys, images):
        with pytest.raises(FileNotFoundError):
            main([images["ext4"], "--cat", "/nope.txt"])


class TestIso:
    def test_ls_inside_a_mounted_iso(self, capsys, images):
        code, out, err = run(capsys, images["iso_inside"],
                             "--iso", "/casper/tiny.iso", "--ls", "")
        assert code == 0
        assert "readme.txt" in out
        assert "ISO:" in err

    def test_cat_inside_a_mounted_iso(self, capsys, images):
        code = main([images["iso_inside"], "--iso", "/casper/tiny.iso",
                     "--cat", "/docs/manual.txt"])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.encode() == SAMPLE["docs/manual.txt"]

    def test_partition_stays_browsable_without_iso(self, capsys, images):
        _code, out, _err = run(capsys, images["iso_inside"], "--ls", "/casper")
        assert "tiny.iso" in out


class TestGuiDispatch:
    def test_gui_flag_hands_the_path_to_the_gui(self, monkeypatch, images):
        pytest.importorskip("tkinter", reason="--gui dispatch needs Tk")
        seen = {}

        def fake_main(argv):
            seen["argv"] = argv
            return 0

        monkeypatch.setattr("vhdpeek.gui.main", fake_main)
        assert main(["--gui", images["ext4"]]) == 0
        assert seen["argv"] == [images["ext4"]]

    def test_gui_flag_without_a_path(self, monkeypatch):
        pytest.importorskip("tkinter", reason="--gui dispatch needs Tk")
        seen = {}
        monkeypatch.setattr("vhdpeek.gui.main",
                            lambda argv: seen.setdefault("argv", argv) or 0)
        assert main(["--gui"]) == 0
        assert seen["argv"] == []


class TestPartSelection:
    def test_chooses_the_first_partition_with_a_filesystem(self, capsys, images):
        code, out, _err = run(capsys, images["two"], "--ls", "")
        assert code == 0
        assert "readme.txt" in out

    def test_explicit_partition(self, capsys, images):
        code, out, err = run(capsys, images["two"], "--part", "1", "--ls", "")
        assert code == 0
        assert "readme.txt" in out
        assert "Partition 1" in err

    def test_out_of_range_partition_fails(self, capsys, images):
        code, _out, err = run(capsys, images["two"], "--part", "9")
        assert code == 1
        assert "No partition 9" in err


class TestGet:
    def test_get_file_saves_exact_bytes(self, capsys, images, tmp_path):
        dest = tmp_path / "readme.txt"
        code, out, err = run(capsys, images["ext4"], "--get", "/readme.txt",
                             "--out", str(dest))
        assert code == 0
        assert out == ""            # downloads never pollute stdout
        assert dest.read_bytes() == SAMPLE["readme.txt"]
        assert str(dest) in err

    def test_get_file_defaults_to_basename(self, capsys, images, tmp_path,
                                           monkeypatch):
        monkeypatch.chdir(tmp_path)
        code, _out, _err = run(capsys, images["ext4"], "--get", "/readme.txt")
        assert code == 0
        assert (tmp_path / "readme.txt").read_bytes() == SAMPLE["readme.txt"]

    def test_get_file_into_existing_directory(self, capsys, images, tmp_path):
        code, _out, _err = run(capsys, images["ext4"], "--get", "/readme.txt",
                               "--out", str(tmp_path))
        assert code == 0
        assert (tmp_path / "readme.txt").read_bytes() == SAMPLE["readme.txt"]

    def test_get_missing_remote_fails(self, capsys, images, tmp_path):
        dest = tmp_path / "nope.txt"
        code, _out, err = run(capsys, images["ext4"], "--get", "/nope.txt",
                              "--out", str(dest))
        assert code == 1
        assert "nope.txt" in err
        assert not dest.exists()

    def test_get_folder_creates_zip(self, capsys, images, tmp_path):
        dest = tmp_path / "docs.zip"
        code, out, _err = run(capsys, images["ext4"], "--get", "/docs",
                              "--out", str(dest))
        assert code == 0
        assert out == ""
        with zipfile.ZipFile(dest) as archive:
            assert archive.read("manual.txt") == SAMPLE["docs/manual.txt"]

    def test_get_folder_appends_zip_suffix(self, capsys, images, tmp_path):
        code, _out, _err = run(capsys, images["ext4"], "--get", "/docs",
                               "--out", str(tmp_path / "docs"))
        assert code == 0
        assert (tmp_path / "docs.zip").is_file()

    def test_get_folder_defaults_to_name_zip(self, capsys, images, tmp_path,
                                             monkeypatch):
        monkeypatch.chdir(tmp_path)
        code, _out, _err = run(capsys, images["ext4"], "--get", "/docs")
        assert code == 0
        with zipfile.ZipFile(tmp_path / "docs.zip") as archive:
            assert archive.read("manual.txt") == SAMPLE["docs/manual.txt"]

    def test_get_root_as_zip(self, capsys, images, tmp_path):
        dest = tmp_path / "root.zip"
        code, _out, _err = run(capsys, images["ext4"], "--get", "/",
                               "--out", str(dest))
        assert code == 0
        with zipfile.ZipFile(dest) as archive:
            names = set(archive.namelist())
            assert {"readme.txt", "docs/manual.txt",
                    "data/blob.bin"} <= names
            assert archive.read("data/blob.bin") == SAMPLE["data/blob.bin"]

    def test_get_empty_dir_is_kept_in_zip(self, capsys, tmp_path):
        blob = fsgen.build_fat32({"empty/": b"", "full/": b"",
                                  "full/a.txt": b"A"})
        disk = vhdgen.assemble_disk(blob, "mbr", 1)
        image = tmp_path / "empty.vhd"
        image.write_bytes(vhdgen.wrap_fixed_vhd(disk))
        dest = tmp_path / "out.zip"
        code, _out, _err = run(capsys, str(image), "--get", "/",
                               "--out", str(dest))
        assert code == 0
        with zipfile.ZipFile(dest) as archive:
            assert "empty/" in archive.namelist()
            assert archive.read("full/a.txt") == b"A"

    def test_get_refuses_overwrite_without_flag(self, capsys, images,
                                                tmp_path):
        dest = tmp_path / "readme.txt"
        dest.write_bytes(b"old")
        code, _out, err = run(capsys, images["ext4"], "--get", "/readme.txt",
                              "--out", str(dest))
        assert code == 1
        assert "--overwrite" in err
        assert dest.read_bytes() == b"old"

    def test_get_overwrites_with_flag(self, capsys, images, tmp_path):
        dest = tmp_path / "readme.txt"
        dest.write_bytes(b"old")
        code, _out, _err = run(capsys, images["ext4"], "--get", "/readme.txt",
                               "--out", str(dest), "--overwrite")
        assert code == 0
        assert dest.read_bytes() == SAMPLE["readme.txt"]

    def test_get_inside_a_mounted_iso(self, capsys, images, tmp_path):
        dest = tmp_path / "manual.txt"
        code, _out, _err = run(capsys, images["iso_inside"],
                               "--iso", "/casper/tiny.iso",
                               "--get", "/docs/manual.txt",
                               "--out", str(dest))
        assert code == 0
        assert dest.read_bytes() == SAMPLE["docs/manual.txt"]

    def test_out_without_get_is_rejected(self, capsys, images, tmp_path):
        with pytest.raises(SystemExit):
            main([images["ext4"], "--out", str(tmp_path / "x")])
        assert os.listdir(tmp_path) == []

    def test_get_quiet_hides_progress(self, capsys, images, tmp_path):
        dest = tmp_path / "readme.txt"
        code, out, err = run(capsys, images["ext4"], "--get", "/readme.txt",
                             "--out", str(dest), "--quiet")
        assert code == 0
        assert out == ""
        assert dest.read_bytes() == SAMPLE["readme.txt"]
        assert "Saved" not in err
        assert "Source:" in err     # diagnostics stay; only progress is quiet

    def test_get_folder_with_symlinks(self, capsys, tmp_path):
        files = {"docs/": b"", "docs/manual.txt": b"Manual\n"}
        links = {"docs/alias.txt": "manual.txt",
                 "docs/dangling": "nope",
                 "docs/cycle": "cycle",
                 "docs/up": ".."}
        blob = fsgen.build_ext4(files, links=links)
        disk = vhdgen.assemble_disk(blob, "mbr", 1)
        image = tmp_path / "links.vhd"
        image.write_bytes(vhdgen.wrap_fixed_vhd(disk))
        dest = tmp_path / "docs.zip"
        code, out, err = run(capsys, str(image), "--get", "/docs",
                             "--out", str(dest))
        assert code == 0
        assert out == ""
        with zipfile.ZipFile(dest) as archive:
            names = set(archive.namelist())
            assert archive.read("alias.txt") == b"Manual\n"
            assert "dangling" not in names
            assert "cycle" not in names
            assert "up" not in names
        assert "dangling link" in err
        assert "directory link" in err
