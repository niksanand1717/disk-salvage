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


def test_files_are_saved_while_the_scan_is_still_running(tmp_path):
    class Tracked(MemorySource):
        furthest = 0

        def __getitem__(self, k):
            if isinstance(k, slice):
                self.furthest = max(self.furthest, k.stop or 0)
            return super().__getitem__(k)

    src = Tracked(place(FILES, 0x40000))
    read_when_saved = []

    class Sink(CollectingSink):
        def emit(self, kind, **d):
            super().emit(kind, **d)
            if kind == "file":
                read_when_saved.append(src.furthest)

    sink = Sink()
    Carver(src, REG, FolderWriter(str(tmp_path)), sink,
           options=CarveOptions(scan_chunk=4096)).run(REG.resolve_types(None))
    assert len(read_when_saved) == len(FILES)
    assert read_when_saved[0] < 0x10000 < len(src), "the first file must be saved long before the scan ends"
    assert read_when_saved == sorted(read_when_saved)
    assert sink.of("phase") == [{"name": "recovering"}]


def test_same_results_for_any_chunk_size():
    def run(chunk, overlap=False):
        rep = Carver(disk(), REG, DryRunWriter(), options=CarveOptions(scan_chunk=chunk, overlap=overlap)) \
            .run(REG.resolve_types(None))
        return [(r.offset, r.length, r.ext, r.status) for r in rep.files], rep.candidates
    reference = run(1 << 30)                      # one chunk: everything scanned before carving
    for chunk in (512, 4096, 65536):
        assert run(chunk) == reference
        assert run(chunk, overlap=True) == run(1 << 30, overlap=True)


def test_checkpoints_report_the_files_saved_so_far(tmp_path):
    snapshots, t = [], [0.0]

    def clock():
        t[0] += 1.0
        return t[0]
    Carver(disk(), REG, FolderWriter(str(tmp_path)), options=CarveOptions(scan_chunk=4096, checkpoint_every=1),
           checkpoint=lambda files: snapshots.append(len(files)), clock=clock).run(REG.resolve_types(None))
    assert snapshots == sorted(snapshots) and snapshots[-1] == len(FILES)
    assert any(0 < s < len(FILES) for s in snapshots)


def test_bad_sectors_found_while_copying_are_flagged(tmp_path):
    jpeg_len = len(FILES[0][1])

    class BadWhenCopied(MemorySource):
        """The drive fails inside the first JPEG only when the whole file is read (the copy)."""
        def __getitem__(self, k):
            if isinstance(k, slice) and k.start == 0x2000 and k.stop - k.start == jpeg_len:
                self._bad = [(0x2000 + 1024, 512)]
            return super().__getitem__(k)

    src = BadWhenCopied(place(FILES, 0x40000))
    rep = Carver(src, REG, FolderWriter(str(tmp_path)), options=CarveOptions(scan_chunk=4096)).run({"jpg"})
    first = rep.files[0]
    assert first.status == "badsectors" and first.path.endswith("_badsectors.jpg")
    assert (tmp_path / first.path).is_file()


def test_overlapping_hits_skipped_unless_requested():
    inner = make_jpeg(3000, seed=4)
    outer = bytearray(make_mp4(20000))
    outer[4096:4096 + len(inner)] = inner           # a JPEG inside the video's mdat
    src = MemorySource(bytes(outer) + bytes(4096))
    rep, _ = carve(src, None)
    assert [r.ext for r in rep.files] == ["mp4"]
    rep, _ = carve(src, None, overlap=True)
    assert sorted(r.ext for r in rep.files) == ["jpg", "mp4"]
