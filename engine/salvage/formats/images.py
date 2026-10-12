"""Still-image formats: JPEG (+MPO, motion photos), PNG, GIF, BMP, ICO, PSD, SVG, WebP."""
import array
import sys

from salvage.binutil import u16, u32, u64
from salvage.formats.base import GB, IMAGE, LIM_IMG, MB, VIDEO, CarveResult, Signature, fin, register
from salvage.formats.isobmff import parse_bmff


def jpeg_end(src, s, limit):
    """End of one baseline/progressive JPEG starting at s, or None."""
    if src[s] != 0xFF or src[s + 1] != 0xD8:
        return None
    p, seen_sos = s + 2, False
    while p + 2 <= limit:
        if src[p] != 0xFF:
            return None
        m = src[p + 1]
        if m == 0xFF:
            p += 1
            continue
        if m == 0xD9:
            return p + 2 if seen_sos else None
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            p += 2
            continue
        if p + 4 > limit:
            return None
        seg = u16(src, p + 2)
        if seg < 2:
            return None
        p += 2 + seg                        # APP1/EXIF (incl. thumbnail) skipped whole
        if m == 0xDA:                       # entropy-coded data follows SOS
            seen_sos = True
            while True:
                q = src.find(b"\xff", p, limit)
                if q == -1 or q + 1 >= limit:
                    return None
                nb = src[q + 1]
                if nb == 0x00 or 0xD0 <= nb <= 0xD7:
                    p = q + 2
                elif nb == 0xFF:
                    p = q + 1
                else:
                    p = q
                    break
    return None


@register("jpeg", {"jpg": IMAGE, "mpo": IMAGE}, [Signature(b"\xff\xd8\xff")])
def parse_jpeg(src, s, n, nxt):
    limit = min(n, s + LIM_IMG)
    end = jpeg_end(src, s, limit)
    if end is None:
        return None
    ext, status = "jpg", "ok"
    while end + 3 <= limit and src[end:end + 3] == b"\xff\xd8\xff":   # MPO: JPEGs glued after EOI
        e2 = jpeg_end(src, end, limit)
        if e2 is None:
            break
        end, ext = e2, "mpo"
    tail = src[end:min(n, end + 256)]       # motion photo: MP4 right after the JPEG
    i = tail.find(b"ftyp")
    if 4 <= i <= 200:
        r = parse_bmff(src, end + i - 4, n, nxt)
        if r and r.ext in ("mp4", "mov"):
            end, status = r.end, r.status
    return CarveResult(end, ext, status)


@register("png", {"png": IMAGE, "apng": IMAGE}, [Signature(b"\x89PNG\r\n\x1a\n")])
def parse_png(src, s, n, nxt):
    limit = min(n, s + LIM_IMG)
    p, ext = s + 8, "png"
    while p + 12 <= limit:
        ln = u32(src, p)
        ct = src[p + 4:p + 8]
        if ln > 0x7FFFFFFF or not ct.isalpha():
            return None
        if ct == b"acTL":
            ext = "apng"
        p += 12 + ln
        if ct == b"IEND":
            return fin(p, n, ext)
    return None


def _skip_subblocks(src, p, limit):
    while p < limit:
        ln = src[p]
        p += 1
        if ln == 0:
            return p
        p += ln
    return None


@register("gif", {"gif": IMAGE}, [Signature(b"GIF87a"), Signature(b"GIF89a")])
def parse_gif(src, s, n, nxt):
    limit = min(n, s + LIM_IMG)
    flags = src[s + 10]
    p = s + 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    frames = 0
    while p is not None and p < limit:
        b = src[p]
        if b == 0x3B:
            return CarveResult(p + 1, "gif") if frames else None
        if b == 0x21:
            p = _skip_subblocks(src, p + 2, limit)
        elif b == 0x2C:
            lf = src[p + 9]
            p += 10 + (3 * (2 << (lf & 7)) if lf & 0x80 else 0) + 1
            p = _skip_subblocks(src, p, limit)
            frames += 1
        else:
            return None
    return None


DIB_SIZES = (12, 40, 52, 56, 64, 108, 124)


def _q_bmp(src, st, n):
    return u32(src, st + 14, "little") in DIB_SIZES


@register("bmp", {"bmp": IMAGE}, [Signature(b"BM", 0, _q_bmp)])
def parse_bmp(src, s, n, nxt):
    size, res, off, dib = (u32(src, s + 2, "little"), u32(src, s + 6, "little"),
                           u32(src, s + 10, "little"), u32(src, s + 14, "little"))
    if dib not in DIB_SIZES or res != 0 or not 26 <= size <= LIM_IMG:
        return None
    if not 14 + dib <= off <= size:
        return None
    planes, bpp = ((u16(src, s + 26, "little"), u16(src, s + 28, "little")) if dib >= 40
                   else (u16(src, s + 22, "little"), u16(src, s + 24, "little")))
    if planes != 1 or bpp not in (1, 2, 4, 8, 16, 24, 32, 64):
        return None
    return fin(s + size, n, "bmp")


def _q_ico(src, st, n):
    return 1 <= u16(src, st + 4, "little") <= 256 and src[st + 9] == 0


@register("ico", {"ico": IMAGE, "cur": IMAGE},
          [Signature(b"\0\0\x01\0", 0, _q_ico), Signature(b"\0\0\x02\0", 0, _q_ico)])
def parse_ico(src, s, n, nxt):
    typ, cnt = u16(src, s + 2, "little"), u16(src, s + 4, "little")
    if typ not in (1, 2) or not 1 <= cnt <= 256:
        return None
    end = 6 + 16 * cnt
    for i in range(cnt):
        e = s + 6 + 16 * i
        sz, off = u32(src, e + 8, "little"), u32(src, e + 12, "little")
        if src[e + 3] != 0 or sz == 0 or off < 6 + 16 * cnt or off + sz > 16 * MB:
            return None
        end = max(end, off + sz)
    first = s + u32(src, s + 18, "little")
    if not (src[first:first + 4] == b"\x89PNG" or u32(src, first, "little") == 40):
        return None
    return fin(s + end, n, "ico" if typ == 1 else "cur")


@register("psd", {"psd": IMAGE, "psb": IMAGE}, [Signature(b"8BPS")])
def parse_psd(src, s, n, nxt):
    ver = u16(src, s + 4)
    if ver not in (1, 2) or src[s + 6:s + 12] != b"\0" * 6:
        return None
    ch, h, w, d, mode = (u16(src, s + 12), u32(src, s + 14), u32(src, s + 18),
                         u16(src, s + 22), u16(src, s + 24))
    if not (1 <= ch <= 56 and d in (1, 8, 16, 32) and mode <= 9
            and 0 < h <= 300000 and 0 < w <= 300000):
        return None
    ext = "psd" if ver == 1 else "psb"
    p = s + 26
    p += 4 + u32(src, p)                    # color mode data
    p += 4 + u32(src, p)                    # image resources
    p += (4 + u32(src, p)) if ver == 1 else (8 + u64(src, p))   # layers & masks
    if p + 2 > n:
        return CarveResult(n, ext, "partial")
    comp = u16(src, p)
    p += 2
    if comp == 0:
        p += ch * h * ((w * d + 7) // 8)
    elif comp == 1:
        cnt, es = ch * h, (2 if ver == 1 else 4)
        if p + cnt * es > n:
            return CarveResult(n, ext, "partial")
        code = "H" if es == 2 else next(c for c in "ILQ" if array.array(c).itemsize == 4)
        a = array.array(code, src[p:p + cnt * es])
        if sys.byteorder == "little":
            a.byteswap()
        p += cnt * es + sum(a)
    else:
        return None
    return fin(p, n, ext) if p - s <= 4 * GB else None


def _q_svg(src, st, n):
    return b"<svg" in src[st:st + 2048]


@register("svg", {"svg": IMAGE}, [Signature(b"<?xml", 0, _q_svg), Signature(b"<svg")])
def parse_svg(src, s, n, nxt):
    limit = min(n, s + 16 * MB)
    if b"<svg" not in src[s:s + 2048]:
        return None
    e = src.find(b"</svg>", s, limit)
    if e == -1:
        return None
    e += 6
    while e < n and src[e] in (0x0A, 0x0D):
        e += 1
    return CarveResult(e, "svg")


@register("riff", {"avi": VIDEO, "webp": IMAGE}, [Signature(b"RIFF")])
def parse_riff(src, s, n, nxt):
    size, form, first = u32(src, s + 4, "little"), src[s + 8:s + 12], src[s + 12:s + 16]
    ok_first = {b"AVI ": {b"LIST", b"JUNK"}, b"WEBP": {b"VP8 ", b"VP8L", b"VP8X"}}
    if form not in ok_first or first not in ok_first[form] or size < 12:
        return None
    end = s + 8 + size + (size & 1)
    if form == b"AVI ":                     # OpenDML: RIFF 'AVIX' chunks follow
        while end + 12 <= n and src[end:end + 4] == b"RIFF" and src[end + 8:end + 12] == b"AVIX":
            sz = u32(src, end + 4, "little")
            end += 8 + sz + (sz & 1)
    return fin(end, n, "avi" if form == b"AVI " else "webp")
