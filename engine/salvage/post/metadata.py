"""Capture dates from recovered files: EXIF (JPEG / TIFF-based RAW) and MP4/MOV headers."""
from __future__ import annotations

import datetime as dt

from salvage.binutil import u16, u32, u64

HEAD = 256 * 1024                       # EXIF lives near the start of a file
MAC_EPOCH = dt.datetime(1904, 1, 1)
TAG_EXIF_IFD, TAG_DATETIME, TAG_ORIGINAL = 0x8769, 0x0132, 0x9003
BMFF_EXTS = {"mp4", "mov", "m4v", "3gp", "3g2", "f4v"}
TIFF_EXTS = {"tif", "dng", "cr2", "nef", "arw", "orf", "rw2", "pef", "srw", "3fr", "erf", "kdc",
             "mrw", "nrw", "sr2", "dcr", "mos", "iiq", "x3f"}


def parse_exif_datetime(text: bytes) -> dt.datetime | None:
    try:
        s = text.split(b"\0")[0].decode("ascii").strip()
        d = dt.datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, UnicodeDecodeError):
        return None
    return d if 1990 <= d.year <= 2100 else None


def tiff_datetime(b: bytes, base: int = 0) -> dt.datetime | None:
    """DateTimeOriginal (else DateTime) from a TIFF structure starting at base."""
    order = b[base:base + 2]
    if order not in (b"II", b"MM"):
        return None
    e = "little" if order == b"II" else "big"
    if u16(b, base + 2, e) != 42:
        return None

    def entries(ifd):
        p = base + ifd
        if p + 2 > len(b):
            return {}
        cnt = min(u16(b, p, e), 512)
        out = {}
        for i in range(cnt):
            q = p + 2 + 12 * i
            if q + 12 > len(b):
                break
            out[u16(b, q, e)] = (u16(b, q + 2, e), u32(b, q + 4, e), q + 8)
        return out

    def text(ent):
        typ, count, at = ent
        if typ != 2 or count < 19:
            return None
        o = at if count <= 4 else base + u32(b, at, e)
        return parse_exif_datetime(b[o:o + count])

    ifd0 = entries(u32(b, base + 4, e))
    if TAG_EXIF_IFD in ifd0:
        exif = entries(u32(b, ifd0[TAG_EXIF_IFD][2], e))
        if TAG_ORIGINAL in exif and (d := text(exif[TAG_ORIGINAL])):
            return d
    if TAG_DATETIME in ifd0:
        return text(ifd0[TAG_DATETIME])
    return None


def jpeg_datetime(b: bytes) -> dt.datetime | None:
    if b[:2] != b"\xff\xd8":
        return None
    p = 2
    while p + 4 <= len(b) and b[p] == 0xFF:
        m, ln = b[p + 1], u16(b, p + 2)
        if m == 0xDA or ln < 2:
            break
        if m == 0xE1 and b[p + 4:p + 10] == b"Exif\0\0":
            return tiff_datetime(b[p + 10:p + 2 + ln])
        p += 2 + ln
    return None


def bmff_datetime(b: bytes, end: int | None = None) -> dt.datetime | None:
    """creation_time of moov/mvhd. b must hold the moov box (it may sit at the file's end)."""
    def walk(p, limit):
        while p + 8 <= limit:
            size, t = u32(b, p), b[p + 4:p + 8]
            hdr = 8
            if size == 1:
                size, hdr = u64(b, p + 8), 16
            elif size == 0:
                size = limit - p
            if size < hdr:
                return None
            if t == b"moov":
                return walk(p + hdr, min(limit, p + size))
            if t == b"mvhd":
                v = b[p + hdr]
                secs = u64(b, p + hdr + 4) if v == 1 else u32(b, p + hdr + 4)
                if not secs:
                    return None
                d = MAC_EPOCH + dt.timedelta(seconds=secs)
                return d if 1990 <= d.year <= 2100 else None
            p += size
        return None
    return walk(0, len(b) if end is None else end)


def file_datetime(path: str, ext: str) -> dt.datetime | None:
    try:
        with open(path, "rb") as f:
            if ext in BMFF_EXTS:
                return _bmff_file_datetime(f)
            head = f.read(HEAD)
    except OSError:
        return None
    if ext in ("jpg", "mpo"):
        return jpeg_datetime(head)
    if ext in TIFF_EXTS:
        return tiff_datetime(head)
    return None


def _bmff_file_datetime(f) -> dt.datetime | None:
    """Walk top-level boxes on disk (mdat can be gigabytes) and parse only moov."""
    size = f.seek(0, 2)
    p = 0
    while p + 8 <= size:
        f.seek(p)
        h = f.read(16)
        ln, t = u32(h, 0), h[4:8]
        hdr = 8
        if ln == 1:
            ln, hdr = u64(h, 8), 16
        elif ln == 0:
            ln = size - p
        if ln < hdr:
            return None
        if t == b"moov":
            f.seek(p)
            return bmff_datetime(f.read(min(ln, 64 * 1024 * 1024)))
        p += ln
    return None
