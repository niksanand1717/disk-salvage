"""Builders for synthetic files, disks and failing drives used across the tests."""
from __future__ import annotations

import random
import struct
import threading
import time
import zlib

from salvage.devices.base import DriveInfo, Platform

SECTOR = 512


# ------------------------------------------------------------------ files
def _noise(n: int, seed: int) -> bytes:
    return random.Random(seed).randbytes(n).replace(b"\xff", b"\xfe")


def _seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def exif_tiff(date: str) -> bytes:
    """Little-endian TIFF: IFD0 -> Exif IFD -> DateTimeOriginal."""
    text = date.encode() + b"\0"
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, 26) + struct.pack("<I", 0)
    exif = struct.pack("<H", 1) + struct.pack("<HHII", 0x9003, 2, len(text), 44) + struct.pack("<I", 0)
    return b"II*\0" + struct.pack("<I", 8) + ifd0 + exif + text


def make_jpeg(size: int = 6000, date: str | None = None, seed: int = 1) -> bytes:
    head = b"\xff\xd8" + _seg(0xE0, b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0")
    if date:
        head += _seg(0xE1, b"Exif\0\0" + exif_tiff(date))
    head += _seg(0xDB, bytes(65)) + _seg(0xC0, bytes([8, 0, 16, 0, 16, 1, 1, 0x11, 0]))
    head += _seg(0xDA, bytes([1, 1, 0, 0, 63, 0]))
    return head + _noise(max(64, size - len(head) - 2), seed) + b"\xff\xd9"


def _chunk(t: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data))


def make_png(size: int = 5000, seed: int = 2) -> bytes:
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", _noise(max(16, size - 8 - 25 - 12 - 12), seed))
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + _chunk(b"IEND", b"")


def _box(t: bytes, data: bytes) -> bytes:
    return struct.pack(">I", 8 + len(data)) + t + data


def make_mp4(size: int = 20000, date_secs: int | None = None, seed: int = 3) -> bytes:
    """ftyp + moov(mvhd) + mdat. date_secs: seconds since 1904 for mvhd.creation_time."""
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    created = date_secs or 0
    mvhd = _box(b"mvhd", struct.pack(">IIIII", 0, created, created, 1000, 5000) + bytes(80))
    moov = _box(b"moov", mvhd)
    mdat = _box(b"mdat", _noise(max(16, size - len(ftyp) - len(moov) - 8), seed))
    return ftyp + moov + mdat


def place(files: list[tuple[int, bytes]], total: int, seed: int = 9) -> bytearray:
    """A disk of `total` noise bytes with each file written at its offset."""
    disk = bytearray(random.Random(seed).randbytes(total))
    for off, data in files:
        disk[off:off + len(data)] = data
    return disk


# ------------------------------------------------------------------ FAT32
class Fat32Builder:
    """A small FAT32 volume with one sub-folder (DCIM) holding the given files.

    512-byte clusters so ~40 MB is already FAT32. Files are stored contiguously.
    """

    def __init__(self, size_mb: int = 40, label: str = "TESTVOL"):
        self.tot = size_mb * 2048
        self.res, self.nf, self.spc = 32, 2, 1
        clusters = self.tot - self.res
        self.fsz = (clusters * 4 + SECTOR - 1) // SECTOR
        self.data_sec = self.res + self.nf * self.fsz
        self.label = label
        self.vol = bytearray(self.tot * SECTOR)
        self.next_cluster = 10
        self.entries: list[bytes] = []
        self.placed: list[tuple[str, int, bytes]] = []     # (name, volume offset, data)

    def cluster_offset(self, c: int) -> int:
        return (self.data_sec + (c - 2) * self.spc) * SECTOR

    @staticmethod
    def _short(name: str, n: int) -> bytes:
        base, _, ext = name.upper().partition(".")
        return (base[:6] + f"~{n}").ljust(8)[:8].encode() + ext[:3].ljust(3).encode()

    @staticmethod
    def _lfn(name: str, short: bytes) -> list[bytes]:
        chk = 0
        for ch in short:
            chk = (((chk & 1) << 7) + (chk >> 1) + ch) & 0xFF
        units = name.encode("utf-16-le") + b"\0\0"
        units += b"\xff" * ((-len(units)) % 26)
        parts = [units[i:i + 26] for i in range(0, len(units), 26)]
        out = []
        for k, p in enumerate(parts, 1):
            seq = k | (0x40 if k == len(parts) else 0)
            out.append(bytes([seq]) + p[:10] + bytes([0x0F, 0, chk]) + p[10:22] + b"\0\0" + p[22:26])
        return list(reversed(out))

    def _entry(self, short: bytes, attr: int, cluster: int, size: int, deleted=False) -> bytes:
        e = bytearray(short + bytes([attr]) + bytes(20))
        e[20:22] = (cluster >> 16).to_bytes(2, "little")
        e[26:28] = (cluster & 0xFFFF).to_bytes(2, "little")
        e[28:32] = size.to_bytes(4, "little")
        if deleted:
            e[0] = 0xE5
        return bytes(e)

    def add_file(self, name: str, data: bytes, deleted: bool = False) -> int:
        c = self.next_cluster
        off = self.cluster_offset(c)
        self.vol[off:off + len(data)] = data
        self.next_cluster += (len(data) + SECTOR - 1) // SECTOR + 3      # small gaps between files
        short = self._short(name, len(self.entries) + 1)
        lfn = self._lfn(name, short)
        if deleted:
            lfn = [bytes([0xE5]) + x[1:] for x in lfn]
        self.entries += lfn + [self._entry(short, 0x20, c, len(data), deleted)]
        self.placed.append((name, off, data))
        return off

    def build(self) -> bytes:
        b = bytearray(SECTOR)
        b[0:3] = b"\xeb\x58\x90"
        b[3:11] = b"MSWIN4.1"
        struct.pack_into("<HBHBHHBH", b, 11, SECTOR, self.spc, self.res, self.nf, 0, 0, 0xF8, 0)
        struct.pack_into("<II", b, 32, self.tot, self.fsz)
        struct.pack_into("<I", b, 44, 2)                   # root cluster
        struct.pack_into("<HH", b, 48, 1, 6)               # FSInfo, backup boot sector
        b[66] = 0x29
        struct.pack_into("<I", b, 67, 0x1234ABCD)
        b[71:82] = self.label.ljust(11).encode()
        b[82:90] = b"FAT32   "
        b[510:512] = b"\x55\xaa"
        self.vol[0:SECTOR] = b
        self.vol[6 * SECTOR:7 * SECTOR] = b
        for k in range(self.nf):
            fo = (self.res + k * self.fsz) * SECTOR
            self.vol[fo:fo + 12] = struct.pack("<III", 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFFF)
        root = self.cluster_offset(2)
        self.vol[root:root + 32] = self.label.ljust(11).encode() + b"\x08" + bytes(20)
        self.vol[root + 32:root + 64] = self._entry(b"DCIM       ", 0x10, 3, 0)
        dcim = bytearray(self._entry(b".          ", 0x10, 3, 0) + self._entry(b"..         ", 0x10, 0, 0))
        dcim += b"".join(self.entries)
        assert len(dcim) <= SECTOR, "too many files for one directory cluster"
        d = self.cluster_offset(3)
        self.vol[d:d + len(dcim)] = dcim
        return bytes(self.vol)


def mbr_disk(volume: bytes, start_lba: int = 2048, ptype: int = 0x0C, extra: int = 0) -> bytearray:
    disk = bytearray(start_lba * SECTOR) + bytearray(volume) + bytearray(extra)
    e = bytearray(16)
    e[0], e[4] = 0x80, ptype
    struct.pack_into("<II", e, 8, start_lba, len(volume) // SECTOR)
    disk[446:462] = e
    struct.pack_into("<I", disk, 440, 0xCAFEF00D)
    disk[510:512] = b"\x55\xaa"
    return disk


# ------------------------------------------------------------ failing drive
class FakeDrive:
    """In-memory disk with injectable faults. Shared by every handle opened on it."""

    def __init__(self, data: bytes, bad: set[int] | None = None, ident=("ACME", "Disk", "SN1")):
        self.data = bytes(data)
        self.bad = set(bad or ())          # sector numbers that always fail
        self.ident = ident
        self.connected = True
        self.drop_at: dict[int, int] = {}  # sector -> how many reads disconnect the drive
        self.hang_at: dict[int, int] = {}  # sector -> how many reads hang
        self.hang_seconds = 5.0
        self.reads = 0
        self.bytes_read = 0
        self.lock = threading.Lock()


class FakeHandle:
    def __init__(self, drive: FakeDrive):
        self.drive, self.pos, self.closed = drive, 0, False

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else len(self.drive.data) + off
        return self.pos

    def read(self, n):
        d = self.drive
        if self.closed:
            raise OSError(9, "closed handle")
        if not d.connected:
            raise OSError(6, "device gone")
        first, last = self.pos // SECTOR, (self.pos + n - 1) // SECTOR
        with d.lock:
            d.reads += 1
            for s in range(first, last + 1):
                if d.hang_at.get(s, 0) > 0:
                    d.hang_at[s] -= 1
                    hang = True
                    break
                if d.drop_at.get(s, 0) > 0:
                    d.drop_at[s] -= 1
                    d.connected = False
                    raise OSError(6, "device gone")
            else:
                hang = False
        if hang:
            time.sleep(d.hang_seconds)
            raise OSError(5, "late failure")
        if any(s in d.bad for s in range(first, last + 1)):
            raise OSError(5, "I/O error (bad sector)")
        out = d.data[self.pos:self.pos + n]
        self.pos += len(out)
        d.bytes_read += len(out)
        return out

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakePlatform(Platform):
    """Drives at fake://N paths; `disk_of` maps output folders to drive paths."""

    def __init__(self, drives: dict[str, FakeDrive] | None = None, disk_of: dict[str, str] | None = None):
        self.drives = drives or {}
        self.disk_of = disk_of or {}

    def list_drives(self):
        return [DriveInfo(p, len(d.data), " ".join(d.ident[:2]), d.ident[2]) for p, d in self.drives.items()]

    def is_device_path(self, path):
        return path.startswith("fake://")

    def open_device(self, path):
        d = self.drives.get(path)
        if d is None or not d.connected:
            raise FileNotFoundError(path)
        return FakeHandle(d)

    def device_size(self, f):
        return len(f.drive.data)

    def identity(self, f, path):
        return f.drive.ident

    def is_disconnect(self, f, path, ex, expected_size):
        d = self.drives.get(path)
        return d is None or not d.connected

    def candidate_paths(self, path):
        return list(self.drives)

    def disk_of_path(self, path):
        for prefix, disk in self.disk_of.items():
            if path.startswith(prefix):
                return disk
        return None
