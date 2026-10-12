"""Box-based containers: MP4/MOV/3GP/HEIC/AVIF/CR3 (ISO BMFF) and JPEG 2000 / JPEG XL."""
from salvage.binutil import u32, u64
from salvage.formats.base import IMAGE, LIM_BIG, LIM_RAW, VIDEO, CarveResult, Signature, register


def walk_boxes(src, s, n, allowed, limit, on_zero):
    p, seen = s, set()
    while p + 8 <= n and p < limit:
        size, t = u32(src, p), src[p + 4:p + 8]
        if t not in allowed:
            break
        hdr = 8
        if size == 1:
            if p + 16 > n:
                return n, seen | {t}, "partial"
            size, hdr = u64(src, p + 8), 16
        elif size == 0:                     # "rest of file" box
            seen.add(t)
            end, st = on_zero(p + 8)
            return end, seen, st
        if size < hdr:
            break
        seen.add(t)
        p += size
    if p > n:
        return n, seen, "partial"
    return p, seen, "ok"


BMFF_TOP = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"uuid", b"meta",
            b"pnot", b"udta", b"moof", b"mfra", b"sidx", b"ssix", b"styp", b"pdin",
            b"prft", b"emsg", b"meco"}
HEIF_BRANDS = {"heic", "heix", "heim", "heis", "hevc", "hevx", "mif1", "msf1", "mif2"}
AUDIO_BRANDS = {"m4a", "m4b", "m4p", "f4a", "f4b"}


def bmff_ext(brand):
    b = brand.decode("latin1").strip().lower()
    if b == "qt":
        return "mov"
    if b in HEIF_BRANDS:
        return "heic"
    if b in ("avif", "avis"):
        return "avif"
    if b.startswith("3g2"):
        return "3g2"
    if b.startswith("3g"):
        return "3gp"
    if b == "crx":
        return "cr3"
    if b.startswith("m4v"):
        return "m4v"
    if b == "f4v":
        return "f4v"
    if b in AUDIO_BRANDS:
        return None
    return "mp4"


@register("bmff",
          {"mp4": VIDEO, "mov": VIDEO, "m4v": VIDEO, "3gp": VIDEO, "3g2": VIDEO, "f4v": VIDEO,
           "heic": IMAGE, "avif": IMAGE, "cr3": IMAGE},
          [Signature(b"ftyp", 4), Signature(b"moov", 4), Signature(b"wide", 4),
           Signature(b"mdat", 4), Signature(b"free", 4), Signature(b"skip", 4)])
def parse_bmff(src, s, n, nxt):
    first = src[s + 4:s + 8]
    if first == b"ftyp":
        if not 16 <= u32(src, s) <= 4096:
            return None
        ext = bmff_ext(src[s + 8:s + 12])
        if not ext:
            return None
    elif first in (b"moov", b"wide", b"mdat", b"free", b"skip"):
        ext = "mov"                         # old QuickTime: no ftyp box
    else:
        return None
    end, seen, st = walk_boxes(src, s, n, BMFF_TOP, s + LIM_BIG,
                               lambda q: (min(n, max(q, nxt)), "approx"))
    if not seen & {b"moov", b"meta", b"moof"}:
        return None
    if first != b"ftyp" and not {b"moov", b"mdat"} <= seen:
        return None
    return CarveResult(end, ext, st)


JP_BOXES = {b"jP  ", b"ftyp", b"jp2h", b"jp2c", b"jp2i", b"xml ", b"uuid", b"uinf",
            b"res ", b"rreq", b"asoc", b"jpch", b"jplh", b"cgrp", b"ftbl", b"dtbl",
            b"free", b"jxlc", b"jxlp", b"jxll", b"jxli", b"jbrd", b"Exif", b"brob",
            b"JXL ", b"colr"}


@register("jp2", {"jp2": IMAGE, "jpx": IMAGE, "jxl": IMAGE},
          [Signature(b"\0\0\0\x0cjP  \r\n\x87\n"), Signature(b"\0\0\0\x0cJXL \r\n\x87\n")])
def parse_jp2(src, s, n, nxt):
    limit = min(n, s + LIM_RAW)

    def to_eoc(q):                          # jp2c with size 0: J2K ends at EOC FFD9
        e = src.find(b"\xff\xd9", q, limit)
        return (e + 2, "ok") if e != -1 else (n, "partial")

    end, seen, st = walk_boxes(src, s, n, JP_BOXES, limit, to_eoc)
    if src[s + 4:s + 8] == b"JXL ":
        ext, need = "jxl", {b"jxlc", b"jxlp"}
    else:
        ext, need = ("jpx" if src[s + 20:s + 24] == b"jpx " else "jp2"), {b"jp2c"}
    return CarveResult(end, ext, st) if seen & need else None
