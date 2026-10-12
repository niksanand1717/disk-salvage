"""TIFF-based camera RAW (DNG, CR2, NEF, ARW, ORF, RW2, PEF, ...) and Fujifilm RAF."""
from salvage.binutil import u16, u32
from salvage.formats.base import IMAGE, LIM_RAW, MB, CarveResult, Signature, fin, register

TIFF_TS = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
MAKE_EXT = [(b"NIKON", "nef"), (b"SONY", "arw"), (b"PENTAX", "pef"), (b"RICOH", "pef"),
            (b"SAMSUNG", "srw"), (b"OLYMPUS", "orf"), (b"OM Digital", "orf"),
            (b"Panasonic", "rw2"), (b"Hasselblad", "3fr"), (b"Phase One", "iiq"),
            (b"SEIKO EPSON", "erf"), (b"EPSON", "erf"), (b"KODAK", "dcr"),
            (b"Kodak", "dcr"), (b"Mamiya", "mef")]
TIFF_EXTS = ["tif", "dng", "cr2", "nef", "arw", "orf", "rw2", "pef", "srw", "3fr",
             "iiq", "erf", "dcr", "mef"]


def _tiff_vals(src, p, typ, c, e):
    w = 2 if typ == 3 else 4 if typ in (4, 13) else 0
    if not w:
        return []
    b = src[p:p + w * c]
    return [int.from_bytes(b[i:i + w], e) for i in range(0, len(b) - w + 1, w)]


@register("tiff", {x: IMAGE for x in TIFF_EXTS},
          [Signature(b"II*\0"), Signature(b"MM\0*"), Signature(b"IIRO"),
           Signature(b"IIRS"), Signature(b"IIU\0")])
def parse_tiff(src, s, n, nxt):
    e = {b"II": "little", b"MM": "big"}.get(src[s:s + 2])
    if not e:
        return None
    magic = u16(src, s + 2, e)
    if magic not in (42, 0x4F52, 0x5352, 0x55):
        return None
    limit = min(n, s + LIM_RAW)
    first = u32(src, s + 4, e)
    if first < 8 or s + first + 2 > limit:
        return None
    end, make, dng, open_from = 8, b"", False, None
    queue, seen, nifd = [first], set(), 0
    while queue and nifd < 64:
        off = queue.pop(0)
        if off in seen or off < 8 or s + off + 2 > limit:
            continue
        seen.add(off)
        nifd += 1
        cnt = u16(src, s + off, e)
        if not 1 <= cnt <= 1000 or s + off + 6 + 12 * cnt > limit:
            if nifd == 1:
                return None
            continue
        end = max(end, off + 6 + 12 * cnt)
        bad, so, sc, jo, jl = 0, None, None, None, None
        for i in range(cnt):
            ent = s + off + 2 + 12 * i
            tag, typ, c = u16(src, ent, e), u16(src, ent + 2, e), u32(src, ent + 4, e)
            ts = TIFF_TS.get(typ)
            if ts is None:
                bad += 1
                continue
            sz, vp = ts * c, ent + 8 - s
            if sz > 4:
                vo = u32(src, ent + 8, e)
                if vo + sz > LIM_RAW:
                    bad += 1
                    continue
                end, vp = max(end, vo + sz), vo
            if tag == 0x010F:
                make = src[s + vp:s + vp + min(sz, 32)]
            elif tag == 0xC612:
                dng = True
            elif tag in (0x0111, 0x0144, 0x0117, 0x0145, 0x0201, 0x0202,
                         0x014A, 0x8769, 0x8825, 0xA005):
                v = _tiff_vals(src, s + vp, typ, min(c, 65536), e)
                if tag in (0x0111, 0x0144):
                    so = v
                elif tag in (0x0117, 0x0145):
                    sc = v
                elif tag == 0x0201:
                    jo = v[0] if v else None
                elif tag == 0x0202:
                    jl = v[0] if v else None
                else:
                    queue.extend(v)             # SubIFDs / EXIF / GPS / Interop
        if nifd == 1 and (cnt < 3 or bad > cnt // 4):
            return None
        if so and sc:
            for o, c in zip(so, sc):
                if o + c <= LIM_RAW:
                    end = max(end, o + c)
        elif so:
            open_from = max(open_from or 0, max(so))
        if jo and jl and jo + jl <= LIM_RAW:
            end = max(end, jo + jl)
        nx = u32(src, s + off + 2 + 12 * cnt, e)
        if nx:
            queue.append(nx)

    if magic in (0x4F52, 0x5352):
        ext = "orf"
    elif magic == 0x55:
        ext = "rw2"
    elif src[s + 8:s + 10] == b"CR":
        ext = "cr2"
    elif dng:
        ext = "dng"
    else:
        ext = next((x for k, x in MAKE_EXT if make.startswith(k)), "tif")
    status = "ok"
    if open_from is not None and open_from >= end:  # raw data with no byte count (e.g. RW2)
        guess = nxt - s if nxt - s > open_from else open_from + 32 * MB
        end, status = max(end, min(guess, LIM_RAW)), "approx"
    return fin(s + end, n, ext, status) if end > 64 else None


@register("raf", {"raf": IMAGE}, [Signature(b"FUJIFILMCCD-RAW")])
def parse_raf(src, s, n, nxt):
    v = [u32(src, s + 84 + 4 * i) for i in range(6)]
    end = 0
    for o, ln in zip(v[0::2], v[1::2]):
        if o and ln:
            if o + ln > LIM_RAW:
                return None
            end = max(end, o + ln)
    return fin(s + end, n, "raf") if end > 160 else None
