"""Identify a filesystem from its boot sector / superblock and check its key structures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from salvage.binutil import KB, MB, hx, u16, u32, u64
from salvage.formats.base import Signature

SECTOR = 512


@dataclass
class FsInfo:
    name: str
    size: int | None = None
    cluster: int | None = None
    notes: list[str] = field(default_factory=list)
    backups: list[int] = field(default_factory=list)   # offsets of backup boot sectors
    meta_ok: bool = False                               # file tables usable?
    data_start: int | None = None                       # FAT: where cluster 2 begins
    label: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def describe_blank(src, off, ln=4096) -> str:
    """Why an expected structure is missing: zeroed, erased (FF), or overwritten."""
    d = src[off:off + ln]
    if not d.strip(b"\0"):
        return "all zeros (wiped / unreadable)"
    if not d.strip(b"\xff"):
        return "all FF (erased flash)"
    return "overwritten with other data"


def _fat_dir_stats(src, p, ln):
    data, live, deleted, label = src[p:p + ln], 0, 0, ""
    for i in range(0, len(data) - 31, 32):
        e = data[i:i + 32]
        if e[0] == 0:
            break
        if e[11] == 0x0F:
            continue
        if e[11] & 0x08:
            if e[0] != 0xE5 and not label:
                label = e[:11].decode("latin1").strip()
        elif e[0] == 0xE5:
            deleted += 1
        elif e[0] != 0x2E:
            live += 1
    return live, deleted, label


def _exfat_dir_stats(src, p, ln):
    data, live, deleted, label, root = src[p:p + ln], 0, 0, "", False
    for i in range(0, len(data) - 31, 32):
        t = data[i]
        if t == 0:
            break
        if t == 0x85:
            live += 1
        elif t == 0x05:
            deleted += 1
        elif t == 0x81:
            root = True
        elif t == 0x83:
            cnt = min(data[i + 1], 11)
            label = data[i + 2:i + 2 + 2 * cnt].decode("utf-16-le", "replace")
    return live, deleted, label, root


def _ntfs_mft_records(src, mft, rec):
    r = bytearray(src[mft:mft + rec])
    uo, uc = u16(r, 4, "little"), u16(r, 6, "little")
    for i in range(1, uc):                  # undo the update-sequence fixups
        if i * 512 <= len(r) and uo + 2 * i + 2 <= len(r):
            r[i * 512 - 2:i * 512] = r[uo + 2 * i:uo + 2 * i + 2]
    p = u16(r, 20, "little")
    while p + 16 <= len(r):
        t, ln = u32(r, p, "little"), u32(r, p + 4, "little")
        if t == 0xFFFFFFFF or ln < 16:
            break
        if t == 0x80 and r[p + 8]:
            return u64(r, p + 48, "little") // rec
        p += ln
    return 0


def probe_ntfs(src, s, n, b):
    le = "little"
    bps, spc = u16(b, 11, le), b[13]
    spc = 1 << (256 - spc) if spc > 0x80 else spc
    if bps not in (512, 1024, 2048, 4096) or not spc:
        return FsInfo("NTFS (boot sector damaged)")
    cl = bps * spc
    size = u64(b, 40, le) * bps
    rs = b[64]
    rec = 1 << (256 - rs) if rs > 0x80 else rs * cl
    info = FsInfo("NTFS", size, cl, [f"volume serial {u64(b, 72, le):016X}"], [s + size])
    mft, mirr = s + u64(b, 48, le) * cl, s + u64(b, 56, le) * cl
    for name, off in (("MFT", mft), ("MFT mirror", mirr)):
        good = off + 4 <= n and src[off:off + 4] == b"FILE"
        info.notes.append(f"{name} at {hx(off)}: {'OK' if good else 'MISSING - ' + describe_blank(src, off)}")
        if good and name == "MFT":
            info.meta_ok = True
            cnt = _ntfs_mft_records(src, mft, rec) if 0 < rec <= 64 * KB else 0
            if cnt:
                info.notes.append(f"MFT holds ~{cnt:,} file records (names, folders, fragment maps)")
    return info


def probe_exfat(src, s, n, b):
    le = "little"
    if not 9 <= b[108] <= 12 or b[108] + b[109] > 25:
        return FsInfo("exFAT (boot sector damaged)")
    bps = 1 << b[108]
    cl = bps << b[109]
    size = u64(b, 72, le) * bps
    heap = s + u32(b, 88, le) * bps
    root = heap + (u32(b, 96, le) - 2) * cl
    live, deleted, label, root_ok = _exfat_dir_stats(src, root, min(cl, MB))
    info = FsInfo("exFAT", size, cl, [f"volume serial {u32(b, 100, le):08X}"], [s + 12 * bps],
                  root_ok, heap, label)
    if label:
        info.notes.insert(0, f'label "{label}"')
    info.notes.append(f"root folder at {hx(root)}: " + (f"{live} files/folders, {deleted} deleted entries"
                                                       if root_ok else "not found (damaged)"))
    bk = s + 12 * bps

    def strip(x):                       # volume flags / percent-in-use may differ
        return x[:106] + x[108:112] + x[113:512]
    info.notes.append(f"backup boot sector at {hx(bk)}: "
                      f"{'OK' if strip(src[bk:bk + 512]) == strip(b) else 'differs / missing'}")
    return info


def probe_fat(src, s, n, b):
    le = "little"
    bps, spc, res, nf = u16(b, 11, le), b[13], u16(b, 14, le), b[16]
    if (b[0] not in (0xEB, 0xE9) or b[510:512] != b"\x55\xaa" or bps not in (512, 1024, 2048, 4096)
            or not spc or spc & (spc - 1) or not res or nf not in (1, 2)):
        return None
    rootent, fat32 = u16(b, 17, le), u16(b, 22, le) == 0
    tot = u16(b, 19, le) or u32(b, 32, le)
    fsz = u16(b, 22, le) or u32(b, 36, le)
    root_secs = (rootent * 32 + bps - 1) // bps
    data_sec = res + nf * fsz + root_secs
    if not tot or not fsz or data_sec >= tot:
        return None
    clusters = (tot - data_sec) // spc
    kind = "FAT12" if clusters < 4085 else "FAT16" if clusters < 65525 else "FAT32"
    cl = bps * spc
    lab_off, ser_off = (71, 67) if fat32 else (43, 39)
    info = FsInfo(kind, tot * bps, cl, [f"volume serial {u32(b, ser_off, le):08X}"],
                  data_start=s + data_sec * bps)
    fat = s + res * bps
    fat_ok = False
    for k in range(nf):
        fo = fat + k * fsz * bps
        good = src[fo] == b[21] and src[fo + 1:fo + 3] == b"\xff\xff"
        fat_ok |= good
        what = "OK" if good else "MISSING - " + describe_blank(src, fo)
        if kind == "FAT32" and fsz * bps <= 64 * MB:
            t = src[fo + 8:fo + fsz * bps]
            used = sum(1 for i in range(0, len(t) - 3, 4) if t[i:i + 4] != b"\0\0\0\0")
            what += f"; {used:,} of {len(t) // 4:,} cluster entries non-zero"
        info.notes.append(f"{'FAT table' if k == 0 else '2nd FAT copy'} at {hx(fo)}: {what}")
    if fat32:
        root, rootlen = s + data_sec * bps + (u32(b, 44, le) - 2) * cl, min(cl, MB)
    else:
        root, rootlen = s + (res + nf * fsz) * bps, root_secs * bps
    live, deleted, label = _fat_dir_stats(src, root, rootlen)
    label = label or b[lab_off:lab_off + 11].decode("latin1").strip()
    if label and label != "NO NAME":
        info.label = label
        info.notes.insert(0, f'label "{label}"')
    root_txt = f"{live} files/folders, {deleted} deleted entries"
    if not live and not deleted:
        root_txt += " - " + describe_blank(src, root, rootlen)
    info.notes.append(f"root folder at {hx(root)}: {root_txt}")
    info.notes.append(f"data area starts at {hx(info.data_start)} (files begin on {cl:,}-byte clusters)")
    bk = u16(b, 50, le) if fat32 else 0
    if 0 < bk < res:
        bko = s + bk * bps
        info.backups.append(bko)
        bkb = src[bko:bko + 512]
        what = ("OK" if bkb[:90] == b[:90] else
                "MISSING - " + describe_blank(src, bko, 512) if bkb[510:512] != b"\x55\xaa" else
                "present but differs from the main one")
        info.notes.append(f"backup boot sector at {hx(bko)}: {what}")
    info.meta_ok = fat_ok or bool(live or deleted)
    return info


def probe_fs(src, s, n) -> FsInfo | None:
    """Identify the filesystem starting at offset s."""
    if s < 0 or s + SECTOR > n:
        return None
    b = src[s:s + SECTOR]
    if b[3:11] == b"NTFS    ":
        return probe_ntfs(src, s, n, b)
    if b[3:11] == b"EXFAT   ":
        return probe_exfat(src, s, n, b)
    fat = probe_fat(src, s, n, b)
    if fat:
        return fat
    if s + 1082 <= n and u16(src, s + 1080, "little") == 0xEF53:
        return FsInfo("ext2/3/4 (Linux)")
    if src[s + 1024:s + 1026] in (b"H+", b"HX"):
        return FsInfo("HFS+ (Mac)")
    if src[s + 32:s + 36] == b"NXSB":
        return FsInfo("APFS (Mac)")
    if src[s + 32769:s + 32774] == b"CD001":
        return FsInfo("ISO 9660 (CD/DVD image)")
    return None


def _q_fatboot(src, st, n):
    b = src[st:st + 512]
    return (len(b) == 512 and b[510:512] == b"\x55\xaa" and b[16] in (1, 2)
            and u16(b, 11, "little") in (512, 1024, 2048, 4096)
            and b[13] != 0 and b[13] & (b[13] - 1) == 0)


# boot-sector signatures: found during the scan, used to report lost volumes
BOOT_SIGNATURES = [Signature(b"NTFS    ", 3), Signature(b"EXFAT   ", 3), Signature(b"\xeb", 0, _q_fatboot)]
