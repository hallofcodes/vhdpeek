"""ext4 reader tests."""

from __future__ import annotations

from vhdpeek.core.partitions import PartitionView, parse_partitions
from vhdpeek.core.volume import BytesView
from vhdpeek.fs.ext4 import Ext4Reader

from tests.fixtures import fsgen
from tests.support import EXPECTED, images, open_disk  # noqa: F401

__all__ = ["images"]

class TestExt4:
    def test_root_listing(self, images):
        reader = Ext4Reader(BytesView(images["raw"]["ext4"]))
        names = {entry.name for entry in reader.list_dir("")}
        assert {"docs", "data", "readme.txt"} <= names

    def test_file_contents(self, images):
        reader = Ext4Reader(BytesView(images["raw"]["ext4"]))
        for path, expected in EXPECTED.items():
            assert reader.read_file(path) == expected, path

    def test_nested(self, images):
        reader = Ext4Reader(BytesView(images["raw"]["ext4"]))
        assert reader.read_file("/data/sub/note.txt") == EXPECTED[
            "/data/sub/note.txt"]

    def test_gpt_partition_filesystem(self, images):
        disk = open_disk(images["containers"]["gpt_ext4"])
        part = parse_partitions(disk)[0]
        reader = Ext4Reader(PartitionView(disk, part))
        assert reader.read_file("/readme.txt") == EXPECTED["/readme.txt"]


LINKED_FILES = {
    "dir/": b"",
    "dir/target.txt": b"through the link\n",
}

LINKED_LINKS = {
    "link.txt": "dir/target.txt",
    "abs.txt": "/dir/target.txt",
    "dangling": "no-such-file",
    "dirlink": "dir",
}


def linked_reader() -> Ext4Reader:
    return Ext4Reader(BytesView(fsgen.build_ext4(LINKED_FILES,
                                                 links=LINKED_LINKS)))


class TestSymlinks:
    def test_valid_link_resolves(self):
        reader = linked_reader()
        assert reader.read_file("/link.txt") == b"through the link\n"
        assert reader.read_file("/abs.txt") == b"through the link\n"
        entry = reader.stat("/link.txt")
        assert entry is not None and not entry.is_dir
        assert entry.size == len(b"through the link\n")

    def test_links_list_as_files(self):
        reader = linked_reader()
        listed = {entry.name: entry for entry in reader.list_dir("")}
        assert not listed["link.txt"].is_dir
        assert not listed["dangling"].is_dir

    def test_dangling_link_has_no_stat(self):
        reader = linked_reader()
        assert reader.stat("/dangling") is None

    def test_link_to_dir_stats_as_dir(self):
        reader = linked_reader()
        entry = reader.stat("/dirlink")
        assert entry is not None and entry.is_dir
