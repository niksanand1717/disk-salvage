"""Video containers: MKV/WebM, FLV, WMV/ASF, MPEG-PS, TS/M2TS, Ogg, RealMedia, MXF, DV."""
from salvage.binutil import u16, u32, u64
from salvage.formats.base import LIM_BIG, MB, VIDEO, CarveResult, Signature, fin, register

SEG_CHILDREN = {0x114D9B74, 0x1549A966, 0x1654AE6B, 0x1F43B675, 0x1C53BB6B,
                0x1941A469, 0x1043A770, 0x1254C367, 0xEC, 0xBF}
CLUSTER_CHILDREN = {0xE7, 0xA3, 0xA0, 0xA7, 0xAB, 0xEC, 0xBF, 0x5854, 0xAF}


def _vint(src, p, keep_marker):
    b = src[p]
    if b == 0:
        return None, 0
    ln = 9 - b.bit_length()
    v = b if keep_marker else b & ((1 << (8 - ln)) - 1)
    for i in range(1, ln):
        v = (v << 8) | src[p + i]
    return v, ln


def _ebml_walk(src, p, limit, n, children, depth):
    while p < limit and p + 2 <= n:
        eid, l1 = _vint(src, p, True)
        if eid is None or eid not in children:
            break
        sz, l2 = _vint(src, p + l1, False)
        if sz is None:
            break
        q = p + l1 + l2
        if sz == (1 << (7 * l2)) - 1:       # unknown size (live recording)
            if eid == 0x1F43B675 and depth == 0:
                p = _ebml_walk(src, q, limit, n, CLUSTER_CHILDREN, 1)
                continue
            break
        p = q + sz
    return p


@register("mkv", {"mkv": VIDEO, "webm": VIDEO}, [Signature(b"\x1a\x45\xdf\xa3")])
def parse_mkv(src, s, n, nxt):
    eid, l1 = _vint(src, s, True)
    sz, l2 = _vint(src, s + l1, False)
    if eid != 0x1A45DFA3 or sz is None or sz > 4096:
        return None
    hdr_end = s + l1 + l2 + sz
    head = src[s:hdr_end]
    ext = "webm" if b"webm" in head else "mkv" if b"matroska" in head else None
    if not ext:
        return None
    eid, l1 = _vint(src, hdr_end, True)
    if eid != 0x18538067:
        return None
    sz, l2 = _vint(src, hdr_end + l1, False)
    body = hdr_end + l1 + l2
    if sz == (1 << (7 * l2)) - 1:
        end = _ebml_walk(src, body, s + LIM_BIG, n, SEG_CHILDREN, 0)
        if end <= body:
            return None
    else:
        end = body + sz
    return fin(end, n, ext)


@register("flv", {"flv": VIDEO}, [Signature(b"FLV\x01")])
def parse_flv(src, s, n, nxt):
    hs = u32(src, s + 5)
    if hs < 9 or hs > 64:
        return None
    p, tags = s + hs + 4, 0
    while p + 11 <= n:
        if src[p] & 0x1F not in (8, 9, 18) or src[p + 8:p + 11] != b"\0\0\0":
            break
        ds = int.from_bytes(src[p + 1:p + 4], "big")
        end = p + 11 + ds + 4
        if end > n:
            return CarveResult(n, "flv", "partial")
        if u32(src, end - 4) != 11 + ds:
            break
        p, tags = end, tags + 1
    return CarveResult(p, "flv") if tags >= 2 else None


ASF_HDR = bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C")
ASF_DATA = bytes.fromhex("3626B2758E66CF11A6D900AA0062CE6C")
ASF_IDX = {bytes.fromhex(h) for h in ("90080033B1E5CF1189F400A0C90349CB",
                                       "D329E2D6DA35D111903400A0C90349BE",
                                       "F803B1FEAD12644C840F2A1D2F7AD48C",
                                       "D03FB73C4A0C0348953DEDF7B6228F0C")}
ASF_VIDEO = bytes.fromhex("C0EF19BC4D5BCF11A8FD00805F5C442B")


@register("asf", {"wmv": VIDEO}, [Signature(ASF_HDR)])
def parse_asf(src, s, n, nxt):
    hs = u64(src, s + 16, "little")
    if not 30 <= hs <= 16 * MB or ASF_VIDEO not in src[s:s + hs]:
        return None                          # audio-only WMA is skipped
    p, got = s + hs, False
    while p + 24 <= n:
        g = src[p:p + 16]
        if g == ASF_DATA:
            got = True
        elif g not in ASF_IDX:
            break
        sz = u64(src, p + 16, "little")
        if sz < 24:
            break
        p += sz
    return fin(p, n, "wmv") if got else None


@register("mpegps", {"mpg": VIDEO}, [Signature(b"\0\0\x01\xba")])
def parse_mpegps(src, s, n, nxt):
    limit = min(n, s + LIM_BIG)
    p, packs, video = s, 0, False
    while p + 6 <= limit:
        if src[p:p + 3] != b"\0\0\x01":
            break
        sid = src[p + 3]
        if sid == 0xBA:
            b4 = src[p + 4]
            if b4 >> 6 == 1:
                p += 14 + (src[p + 13] & 7)  # MPEG-2 pack header
            elif b4 >> 4 == 2:
                p += 12                     # MPEG-1 pack header
            else:
                break
            packs += 1
        elif sid == 0xB9:
            p += 4
            break
        elif sid >= 0xBB:
            if 0xE0 <= sid <= 0xEF:
                video = True
            p += 6 + u16(src, p + 4)
        else:
            break
    return fin(p, n, "mpg") if packs >= 2 and video else None


def _parse_ts(src, s, n, pkt, off, ext):
    limit = min(n, s + LIM_BIG)
    if s + pkt * 8 > n:
        return None
    if any(src[s + off + i * pkt] != 0x47 for i in range(8)):
        return None
    if src[s + off + 1] == 0x47 and src[s + off + 2] == 0x47:
        return None                         # just a run of 'G' bytes
    p, step = s, pkt * 8192
    while p < limit:
        blk = src[p:min(limit, p + step)]
        k = len(blk) // pkt
        if k == 0:
            break
        col = blk[off::pkt][:k]
        good = k - len(col.lstrip(b"\x47"))
        p += good * pkt
        if good < k:
            break
    return CarveResult(p, ext)


def _q_ts(src, st, n):
    return st + 377 < n and src[st + 188] == 0x47 and src[st + 376] == 0x47


def _q_m2ts(src, st, n):
    return st + 389 < n and src[st + 196] == 0x47 and src[st + 388] == 0x47


@register("ts", {"ts": VIDEO}, [Signature(b"\x47", 0, _q_ts)])
def parse_ts(src, s, n, nxt):
    return _parse_ts(src, s, n, 188, 0, "ts")


@register("m2ts", {"m2ts": VIDEO}, [Signature(b"\x47", 4, _q_m2ts)])
def parse_m2ts(src, s, n, nxt):
    return _parse_ts(src, s, n, 192, 4, "m2ts")


@register("ogg", {"ogv": VIDEO}, [Signature(b"OggS\0\x02")])
def parse_ogg(src, s, n, nxt):
    p, ext, pages = s, None, 0
    while p + 27 <= n and src[p:p + 5] == b"OggS\0":
        ns = src[p + 26]
        body = p + 27 + ns
        if body > n:
            return CarveResult(n, ext, "partial") if ext else None
        if src[p + 5] & 2:                  # BOS page: which codec?
            h = src[body:body + 8]
            if h.startswith((b"\x80theora", b"OVP80", b"\x01video", b"\x80daala")):
                ext = "ogv"
        p, pages = body + sum(src[p + 27:body]), pages + 1
    return fin(p, n, ext) if ext and pages >= 2 else None


RM_IDS = {b".RMF", b"PROP", b"MDPR", b"CONT", b"DATA", b"INDX", b"RMMD", b"RJMD"}


@register("rm", {"rm": VIDEO}, [Signature(b".RMF")])
def parse_rm(src, s, n, nxt):
    p, seen, video = s, set(), False
    while p + 10 <= n:
        cid = src[p:p + 4]
        if cid not in RM_IDS:
            break
        sz = u32(src, p + 4)
        if sz < 8:
            break
        if cid == b"MDPR" and b"video" in src[p:p + min(sz, 1024)]:
            video = True
        seen.add(cid)
        if cid == b"DATA":                  # size field is unreliable: walk packets
            q, npk = p + 18, u32(src, p + 10)
            for _ in range(npk):
                if q + 4 > n or u16(src, q) not in (0, 1) or u16(src, q + 2) < 12:
                    break
                q += u16(src, q + 2)
            else:
                if src[q:q + 8] == b"\0" * 8:     # empty trailer some muxers write
                    q += 8
                p = q
                continue
        p += sz
    return fin(p, n, "rm") if video and b"DATA" in seen else None


@register("mxf", {"mxf": VIDEO},
          [Signature(b"\x06\x0e\x2b\x34\x02\x05\x01\x01\x0d\x01\x02\x01\x01\x02")])
def parse_mxf(src, s, n, nxt):
    p, k = s, 0
    while p + 17 <= n and src[p:p + 4] == b"\x06\x0e\x2b\x34":
        b = src[p + 16]
        if b < 0x80:
            ln, ll = b, 1
        else:
            m = b & 0x7F
            if not 1 <= m <= 8:
                break
            ln, ll = int.from_bytes(src[p + 17:p + 17 + m], "big"), 1 + m
        p, k = p + 16 + ll + ln, k + 1
    return fin(p, n, "mxf") if k >= 4 else None


def _q_dv(src, st, n):
    return src[st + 3] & 0x7F == 0x3F


@register("dv", {"dv": VIDEO}, [Signature(b"\x1f\x07\x00", 0, _q_dv)])
def parse_dv(src, s, n, nxt):
    dsf = src[s + 3] >> 7
    fs = 144000 if dsf else 120000          # PAL vs NTSC frame size
    p, frames = s, 0
    while (p + 4 <= n and src[p] == 0x1F and src[p + 1] == 0x07 and src[p + 2] == 0x00
           and src[p + 3] & 0x7F == 0x3F and src[p + 3] >> 7 == dsf):
        p, frames = p + fs, frames + 1
    return fin(p, n, "dv") if frames >= 2 else None
