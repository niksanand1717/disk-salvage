import hashlib
import os
from collections import namedtuple

import pytest

from helpers import make_jpeg, make_mp4, make_png, place
from salvage.carving import CarveOptions, Carver, DryRunWriter, FolderWriter, Scanner
from salvage.errors import OutOfSpace
from salvage.events import CancelToken, CollectingSink
from salvage.formats import Signature, default_registry
from salvage.sources import MemorySource

REG = default_registry()
FILES = [(0x2000, make_jpeg(9000, seed=1)), (0x8000, make_png(6000)), (0x10000, make_mp4(40000)),
         (0x30000, make_jpeg(5000, seed=7))]
Usage = namedtuple("Usage", "total used free")


def disk(bad=None):
    return MemorySource(place(FILES, 0x40000), bad=bad)


def carve(src, out, wanted=None, **kw):
    sink = CollectingSink()
    rep = Carver(src, REG, FolderWriter(str(out)) if out else DryRunWriter(), sink,
                 options=CarveOptions(**kw)).run(wanted or REG.resolve_types(None))
    return rep, sink


def test_recovers_every_file_byte_exact(tmp_path):
    rep, sink = carve(disk(), tmp_path)
    got = {r.offset: r for r in rep.files}
    for off, data in FILES:
        r = got[off]
        assert r.length == len(data) and r.status == "ok"
        assert r.sha256 == hashlib.sha256(data).hexdigest()
        with open(tmp_path / r.path, "rb") as f:
            assert f.read() == data
    assert rep.stats == {"jpg": 2, "png": 1, "mp4": 1}
    assert len(sink.of("file")) == 4
    assert not any(p.endswith(".part") for _, _, fs in os.walk(tmp_path) for p in fs)


def test_type_filter_and_min_size(tmp_path):
    rep, _ = carve(disk(), None, {"jpg"}, min_size=6000)
    assert [r.offset for r in rep.files] == [0x2000]


def test_bad_sectors_flagged(tmp_path):
    rep, _ = carve(disk(bad=[(0x2000 + 1024, 512)]), tmp_path)
    st = {r.offset: r.status for r in rep.files}
    assert st[0x2000] == "badsectors" and st[0x8000] == "ok"
    assert "_badsectors" in next(r.path for r in rep.files if r.offset == 0x2000)


def test_out_of_space_stops_cleanly(tmp_path):
    free = iter([10 ** 9, 10 ** 9] + [1000] * 10)
    writer = FolderWriter(str(tmp_path), reserve_bytes=0, disk_usage=lambda p: Usage(0, 0, next(free)))
    sink = CollectingSink()
    rep = Carver(disk(), REG, writer, sink).run(REG.resolve_types(None))
    assert len(rep.files) == 2
    assert "free" in rep.stopped
    assert sink.of("warning")


def test_writer_raises_out_of_space(tmp_path):
    w = FolderWriter(str(tmp_path), reserve_bytes=100, disk_usage=lambda p: Usage(0, 0, 150))
    with pytest.raises(OutOfSpace):
        w.save(MemorySource(b"x" * 100), 0, 100, "jpg", "ok", 1)


def test_cancel():
    tok = CancelToken()
    tok.cancel()
    rep = Carver(disk(), REG, DryRunWriter(), cancel=tok).run({"jpg"})
    assert rep.stopped == "cancelled"


def test_scanner_alignment_and_chunks():
    src = disk()
    sigs = [(Signature(b"\xff\xd8\xff"), "jpeg")]
    for chunk in (512, 4096, 1 << 20):
        assert Scanner(src, 512, chunk).scan(sigs) == [(0x2000, "jpeg"), (0x30000, "jpeg")]
    data = bytearray(4096)
    data[100:103] = b"\xff\xd8\xff"                 # not sector-aligned
    assert Scanner(MemorySource(data), 512).scan(sigs) == []
    assert Scanner(MemorySource(data), 1).scan(sigs) == [(100, "jpeg")]


def test_overlapping_hits_skipped_unless_requested():
    inner = make_jpeg(3000, seed=4)
    outer = bytearray(make_mp4(20000))
    outer[4096:4096 + len(inner)] = inner           # a JPEG inside the video's mdat
    src = MemorySource(bytes(outer) + bytes(4096))
    rep, _ = carve(src, None)
    assert [r.ext for r in rep.files] == ["mp4"]
    rep, _ = carve(src, None, overlap=True)
    assert sorted(r.ext for r in rep.files) == ["jpg", "mp4"]
