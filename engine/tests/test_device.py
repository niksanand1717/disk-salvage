"""DeviceSource against a simulated failing drive: bad sectors, dropouts, hangs."""
import pytest

from helpers import SECTOR, FakeDrive, FakePlatform, make_jpeg, place
from salvage.errors import SourceUnavailable
from salvage.events import Cancelled, CancelToken, CollectingSink
from salvage.sources import DeviceSource, open_source

DATA = bytes(place([(0x3000, make_jpeg(5000))], 3 * 1024 * 1024))


def dev(drive, **kw):
    plat = FakePlatform({"fake://0": drive})
    sink = CollectingSink()
    kw.setdefault("read_timeout", None)
    src = DeviceSource("fake://0", plat, sink, sleep=kw.pop("sleep", lambda s: None), **kw)
    src.BLOCK = 64 * 1024
    return src, sink


def test_reads_like_bytes():
    src, _ = dev(FakeDrive(DATA))
    assert len(src) == len(DATA)
    assert src[0x3000:0x3010] == DATA[0x3000:0x3010]
    assert src[5] == DATA[5] and src[-1] == DATA[-1]
    a, b = 60 * 1024, 200 * 1024                     # spans several blocks
    assert src[a:b] == DATA[a:b]
    assert src.find(b"\xff\xd8\xff") == DATA.find(b"\xff\xd8\xff")
    needle = DATA[64 * 1024 - 3:64 * 1024 + 5]       # straddles a block boundary
    assert src.find(needle, 1000) == DATA.find(needle, 1000)


def test_bad_sectors_read_as_zeros_and_are_listed():
    bad = {100, 101, 300}
    src, _ = dev(FakeDrive(DATA, bad=bad))
    blob = src[0:400 * SECTOR]
    assert blob[100 * SECTOR:102 * SECTOR] == bytes(2 * SECTOR)
    assert blob[102 * SECTOR:103 * SECTOR] == DATA[102 * SECTOR:103 * SECTOR]
    assert src.bad_ranges() == [(100 * SECTOR, 2 * SECTOR), (300 * SECTOR, SECTOR)]


def test_waits_for_a_dropped_drive_and_continues():
    drive = FakeDrive(DATA)
    drive.drop_at[2000] = 1

    def replug(_):
        drive.connected = True
    src, sink = dev(drive, sleep=replug)
    assert src[2000 * SECTOR:2001 * SECTOR] == DATA[2000 * SECTOR:2001 * SECTOR]
    assert sink.of("drive_lost") and sink.of("drive_back")
    assert not src.bad_ranges()


def test_area_that_keeps_dropping_is_skipped():
    drive = FakeDrive(DATA)
    drive.drop_at[2000] = 10 ** 6

    def replug(_):
        drive.connected = True
    src, sink = dev(drive, sleep=replug, max_drops=2)
    blk = src.load_block(2000 * SECTOR // src.BLOCK)
    assert blk == bytes(len(blk))
    assert src.bad_ranges() and any("skipping" in w["message"] for w in sink.of("warning"))


def test_hung_read_times_out_and_reopens():
    drive = FakeDrive(DATA)
    drive.hang_at[10] = 1
    drive.hang_seconds = 1.0
    src, sink = dev(drive, read_timeout=0.2)
    assert src[10 * SECTOR:11 * SECTOR] == DATA[10 * SECTOR:11 * SECTOR]
    assert any("did not answer" in w["message"] for w in sink.of("warning"))


def test_waiting_can_be_cancelled():
    drive = FakeDrive(DATA)
    drive.drop_at[2000] = 1
    tok = CancelToken()
    src, _ = dev(drive, sleep=lambda s: tok.cancel(), cancel=tok)
    with pytest.raises(Cancelled):
        src[2000 * SECTOR]


def test_other_drive_is_not_mistaken_for_ours():
    drive = FakeDrive(DATA)
    other = FakeDrive(b"\x01" * 512 + DATA[512:], ident=("ACME", "Disk", "SN2"))
    same_size_same_start = FakeDrive(DATA, ident=("Bridge", "Reports", "Differently"))
    plat = FakePlatform({"fake://0": drive, "fake://1": other, "fake://2": same_size_same_start})
    src = DeviceSource("fake://0", plat, read_timeout=None)
    assert src._try_open("fake://1") is None
    assert src._try_open("fake://0") is not None
    assert src._try_open("fake://2") is not None    # identity can change on replug; sector 0 decides


def test_empty_drive_is_unavailable():
    with pytest.raises(SourceUnavailable):
        DeviceSource("fake://0", FakePlatform({"fake://0": FakeDrive(b"")}))


def test_open_source_picks_the_right_kind(tmp_path):
    p = tmp_path / "img.bin"
    p.write_bytes(DATA)
    plat = FakePlatform({"fake://0": FakeDrive(DATA)})
    assert type(open_source("fake://0", plat)).__name__ == "DeviceSource"
    f = open_source(str(p), plat)
    assert type(f).__name__ == "FileSource" and f[0:16] == DATA[:16]
    f.close()
    with pytest.raises(SourceUnavailable):
        open_source(str(tmp_path / "missing.img"), plat)
