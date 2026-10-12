import json

import pytest

from helpers import SECTOR, FakeDrive, FakePlatform, make_jpeg, place
from salvage.errors import ImageMismatch
from salvage.events import CancelToken
from salvage.imaging import Imager, merge_ranges
from salvage.sources import DeviceSource, FileSource, MemorySource

DATA = bytes(place([(0x3000, make_jpeg(5000))], 1024 * 1024))


class CancelAfterReads(MemorySource):
    """Cancels the job after n block reads (like a user pressing Stop mid-copy)."""

    def __init__(self, data, tok, n):
        super().__init__(data, "mem")
        self.tok, self.n = tok, n

    def __getitem__(self, k):
        if isinstance(k, slice) and k.stop - k.start > 512:
            self.n -= 1
            if self.n <= 0:
                self.tok.cancel()
        return super().__getitem__(k)


def test_full_copy(tmp_path):
    dest = str(tmp_path / "disk.img")
    rep = Imager(MemorySource(DATA, "mem"), dest, block=64 * 1024).run()
    assert rep.done and rep.copied == len(DATA)
    assert open(dest, "rb").read() == DATA
    m = json.load(open(dest + ".map"))
    assert m["done"] and m["pos"] == len(DATA)
    src = FileSource(dest)
    assert not src.incomplete
    src.close()


def test_resume_after_cancel(tmp_path):
    dest = str(tmp_path / "disk.img")
    tok = CancelToken()
    rep = Imager(CancelAfterReads(DATA, tok, 3), dest, cancel=tok, block=64 * 1024).run()
    assert rep.stopped == "cancelled" and 0 < rep.copied < len(DATA)
    part = FileSource(dest)
    assert part.incomplete
    part.close()
    rep = Imager(MemorySource(DATA, "mem"), dest, block=64 * 1024).run()
    assert rep.done and open(dest, "rb").read() == DATA


def test_refuses_another_drives_image(tmp_path):
    dest = str(tmp_path / "disk.img")
    Imager(MemorySource(DATA, "mem"), dest, block=64 * 1024).run()
    with pytest.raises(ImageMismatch):
        Imager(MemorySource(DATA + bytes(512), "mem"), dest).run()
    other = b"\x01" * 512 + DATA[512:]
    with pytest.raises(ImageMismatch):
        Imager(MemorySource(other, "mem"), dest).run()


def test_bad_sectors_recorded_in_map(tmp_path):
    drive = FakeDrive(DATA, bad={40, 41})
    src = DeviceSource("fake://0", FakePlatform({"fake://0": drive}), read_timeout=None)
    src.BLOCK = 64 * 1024
    dest = str(tmp_path / "disk.img")
    rep = Imager(src, dest).run()
    assert rep.done and rep.bad == [(40 * SECTOR, 2 * SECTOR)]
    img = FileSource(dest)
    assert img.bad_ranges() == [(40 * SECTOR, 2 * SECTOR)]
    assert img[40 * SECTOR:42 * SECTOR] == bytes(2 * SECTOR)
    assert img[42 * SECTOR:43 * SECTOR] == DATA[42 * SECTOR:43 * SECTOR]
    img.close()


def test_merge_ranges():
    assert merge_ranges([(10, 5), (0, 4), (14, 10), (40, 1)]) == [[0, 4], [10, 14], [40, 1]]
