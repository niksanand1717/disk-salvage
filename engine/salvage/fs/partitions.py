"""Partition table (MBR / GPT) analysis and the lost-volume search."""
from __future__ import annotations

import uuid
import zlib
from dataclasses import asdict, dataclass, field

from salvage.binutil import human, hx, u32, u64
from salvage.fs.filesystems import SECTOR, FsInfo, probe_fs

MBR_TYPES = {0x01: "FAT12", 0x04: "FAT16 <32M", 0x05: "extended", 0x06: "FAT16",
             0x07: "NTFS/exFAT", 0x0B: "FAT32 (CHS)", 0x0C: "FAT32 (LBA)", 0x0E: "FAT16 (LBA)",
             0x0F: "extended (LBA)", 0x11: "hidden FAT12", 0x14: "hidden FAT16",
             0x16: "hidden FAT16", 0x17: "hidden NTFS/exFAT", 0x1B: "hidden FAT32",
             0x1C: "hidden FAT32 (LBA)", 0x1E: "hidden FAT16 (LBA)", 0x27: "Windows recovery",
             0x82: "Linux swap", 0x83: "Linux", 0x85: "Linux extended", 0x8E: "Linux LVM",
             0xA5: "FreeBSD", 0xAF: "HFS+", 0xEE: "GPT protective", 0xEF: "EFI system",
             0xFD: "Linux RAID"}
EXTENDED = {0x05, 0x0F, 0x85}
GPT_TYPES = {
    "C12A7328-F81F-11D2-BA4B-00A0C93EC93B": "EFI system",
    "E3C9E316-0B5C-4DB8-817D-F92DF00215AE": "Microsoft reserved",
    "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7": "Microsoft basic data",
    "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC": "Windows recovery",
    "0FC63DAF-8483-4772-8E79-3D69D8477DE4": "Linux filesystem",
    "0657FD6D-A4AB-43C4-84E5-0933C84B4F4F": "Linux swap",
    "E6D6D379-F507-44C2-A23C-238F2A3DF928": "Linux LVM",
    "48465300-0000-11AA-AA11-00306543ECAC": "Apple HFS+",
    "7C3457EF-0000-11AA-AA11-00306543ECAC": "Apple APFS",
}


@dataclass
class Volume:
    start: int
    length: int | None
    description: str
    fs: FsInfo | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class LostVolume:
    offset: int
    fs: str
    size: int | None
    hint: str = ""


@dataclass
class DiskReport:
    size: int
    notes: list[str] = field(default_factory=list)
    volumes: list[Volume] = field(default_factory=list)
    verdict: str = ""
    known_boot_offsets: set[int] = field(default_factory=set)
    lost: list[LostVolume] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["known_boot_offsets"] = sorted(self.known_boot_offsets)
        return d

    def fat_volumes(self) -> list[FsInfo]:
        return [v.fs for v in self.volumes if v.fs and v.fs.name.startswith("FAT") and v.fs.data_start]

    def lines(self) -> list[str]:
        L = list(self.notes)
        for v in self.volumes:
            L += ["", v.description, f"  starts at {hx(v.start)}, size {human(v.length)}"]
            L += ["  !! " + w for w in v.warnings]
            if v.fs:
                head = f"  filesystem: {v.fs.name}"
                if v.fs.size:
                    head += f", {human(v.fs.size)}"
                if v.fs.cluster:
                    head += f", cluster {v.fs.cluster:,} bytes"
                L.append(head)
                L += ["  " + x for x in v.fs.notes]
            L += ["  " + x for x in v.notes]
        if self.lost:
            L += ["", "volume boot sectors the partition table does not point to "
                      "(lost/deleted partitions, or disk images stored as files):"]
            L += [f"  {hx(x.offset):>14}  {x.fs:6s} {human(x.size):>10}" + (f"   ({x.hint})" if x.hint else "")
                  for x in self.lost]
        if self.verdict:
            L += ["", "=> " + self.verdict]
        return L


def _walk_ebr(src, n, base, notes):
    vols, cur, seen = [], base, set()
    while cur not in seen and len(seen) < 128 and (cur + 1) * SECTOR <= n:
        seen.add(cur)
        e = src[cur * SECTOR:(cur + 1) * SECTOR]
        if e[510:512] != b"\x55\xaa":
            notes.append(f"extended-partition chain broken at {hx(cur * SECTOR)} (no 55AA)")
            break
        t1, l1, c1 = e[450], u32(e, 454, "little"), u32(e, 458, "little")
        if t1:
            vols.append(Volume((cur + l1) * SECTOR, c1 * SECTOR,
                               f"logical partition, type 0x{t1:02X} {MBR_TYPES.get(t1, 'unknown')}"))
        if not e[466]:
            break
        cur = base + u32(e, 470, "little")
    return vols


def _gpt_header(src, off):
    le = "little"
    h = src[off:off + SECTOR]
    if h[:8] != b"EFI PART":
        return None
    hs = u32(h, 12, le)
    if not 92 <= hs <= SECTOR:
        return None
    raw = bytearray(h[:hs])
    raw[16:20] = bytes(4)
    return {"crc_ok": zlib.crc32(raw) == u32(h, 16, le), "alt": u64(h, 32, le),
            "guid": str(uuid.UUID(bytes_le=bytes(h[56:72]))).upper(),
            "elba": u64(h, 72, le), "num": u32(h, 80, le), "esz": u32(h, 84, le),
            "ecrc": u32(h, 88, le)}


def _read_gpt(src, n, notes, incomplete):
    le = "little"
    p = _gpt_header(src, SECTOR)
    alt = p["alt"] * SECTOR if p else n - SECTOR
    b = _gpt_header(src, alt) if alt + SECTOR <= n else None
    if b is None and alt != n - SECTOR:
        b = _gpt_header(src, n - SECTOR)
    notes.append("GPT primary header: " + ((("OK" if p["crc_ok"] else "CRC BAD") + f", disk GUID {p['guid']}")
                                           if p else "missing"))
    if p and alt + SECTOR > n and not incomplete:
        notes.append(f"!! GPT says the drive is {human(alt + SECTOR)}, but it reports {human(n)}: "
                     "size misreported, or a fake-capacity drive")
    notes.append("GPT backup header: " + (("OK" if b["crc_ok"] else "CRC BAD") if b else "missing"))
    use = next((h for h in (p, b) if h and h["crc_ok"]), p or b)
    if not use:
        return []
    if use is not p:
        notes.append("using the BACKUP GPT (primary is damaged)")
    num, esz = use["num"], use["esz"]
    if not 128 <= esz <= 4096 or not 0 < num <= 1024:
        notes.append("GPT partition entry array header is invalid")
        return []
    ent = src[use["elba"] * SECTOR:use["elba"] * SECTOR + num * esz]
    if zlib.crc32(ent) != use["ecrc"]:
        notes.append("GPT partition entry array CRC BAD (entries may be damaged)")
    vols = []
    for i in range(num):
        e = ent[i * esz:(i + 1) * esz]
        if len(e) < 128 or e[:16] == bytes(16):
            continue
        tg = str(uuid.UUID(bytes_le=bytes(e[:16]))).upper()
        first, last = u64(e, 32, le), u64(e, 40, le)
        name = e[56:128].decode("utf-16-le", "replace").split("\0")[0]
        vols.append(Volume(first * SECTOR, (last - first + 1) * SECTOR,
                           f"GPT #{i + 1} {GPT_TYPES.get(tg, tg)}" + (f' "{name}"' if name else "")))
    return vols


def analyze_disk(src, incomplete: bool = False) -> DiskReport:
    """Partition table(s) and the boot sector of every volume.

    incomplete: the source is a partially copied image (sizes past its end are expected).
    """
    n = len(src)
    rep = DiskReport(size=n, notes=[f"drive size: {human(n)} ({n:,} bytes)"])
    if incomplete:
        rep.notes.append("this image is only partly copied: later areas are missing")
    s0 = src[0:SECTOR]
    fs0 = probe_fs(src, 0, n)
    vols: list[Volume] = []
    if s0 == bytes(SECTOR):
        rep.notes.append("sector 0 is all zeros: partition table wiped (or unreadable)")
    if fs0 and fs0.size:
        rep.notes.append("no partition table: the whole drive is one volume ('superfloppy' layout)")
        vols.append(Volume(0, n, "whole drive"))
    else:
        gpt = src[SECTOR:SECTOR + 8] == b"EFI PART" or src[n - SECTOR:n - SECTOR + 8] == b"EFI PART"
        if s0[510:512] != b"\x55\xaa":
            if s0 != bytes(SECTOR):
                rep.notes.append("sector 0 has no 55AA signature: no valid MBR (overwritten or damaged)")
        else:
            rep.notes.append(f"MBR found, disk signature {u32(s0, 440, 'little'):08X}")
            for i in range(4):
                e = s0[446 + 16 * i:462 + 16 * i]
                typ, lba, cnt = e[4], u32(e, 8, "little"), u32(e, 12, "little")
                if not typ:
                    continue
                if typ == 0xEE:
                    gpt = True
                elif typ in EXTENDED:
                    rep.notes.append(f"MBR #{i + 1}: extended partition at {hx(lba * SECTOR)}")
                    vols += _walk_ebr(src, n, lba, rep.notes)
                else:
                    vols.append(Volume(lba * SECTOR, cnt * SECTOR,
                                       f"MBR #{i + 1} type 0x{typ:02X} {MBR_TYPES.get(typ, 'unknown')}"
                                       + (" (active)" if e[0] == 0x80 else "")))
            if not vols and not gpt:
                rep.notes.append("MBR has no partition entries (partitions deleted?)")
        if gpt:
            vols += _read_gpt(src, n, rep.notes, incomplete)
        if fs0:
            rep.notes.append(f"(the drive also looks like a {fs0.name} from sector 0)")

    meta = wiped = False
    for v in vols:
        if v.length and v.start + v.length > n and not incomplete:
            v.warnings.append(f"partition ends at {human(v.start + v.length)}, past the end of the drive "
                              f"({human(n)}): size misreported, or a fake-capacity drive")
        rep.known_boot_offsets.add(v.start)
        v.fs = probe_fs(src, v.start, n)
        if v.fs:
            rep.known_boot_offsets.update(v.fs.backups)
            meta |= v.fs.meta_ok
            if v.fs.size and v.length and v.fs.size > v.length:
                v.warnings.append(f"filesystem ({human(v.fs.size)}) is bigger than its partition")
            continue
        wiped = True
        v.notes.append("no recognizable filesystem at its start (boot sector wiped / damaged)")
        for name, off in (("FAT32 backup", v.start + 6 * SECTOR), ("exFAT backup", v.start + 12 * SECTOR),
                          ("NTFS backup", v.start + v.length - SECTOR if v.length else -1)):
            fb = probe_fs(src, off, n)
            if fb and fb.size:
                rep.known_boot_offsets.add(off)
                v.notes.append(f"but a {name} boot sector survives at {hx(off)}: {fb.name} "
                               f"{human(fb.size)} -> the volume can be rebuilt from it")
    rep.volumes = vols
    if not vols:
        rep.verdict = ("no usable partition table. Carving is the way; the scan also looks "
                       "for boot sectors of lost volumes.")
    elif meta:
        rep.verdict = ("filesystem metadata (MFT / FAT / folders) is at least partly intact: original "
                       "names and folders may be recoverable. Carving still finds files whose entries are gone.")
    elif wiped:
        rep.verdict = "the partition table survives but the filesystem start is damaged: carving is the main option."
    else:
        rep.verdict = ("the partition table and boot sector are fine, but the file tables (FAT / MFT / "
                       "folders) are gone. Carving is the way to get the files back.")
    return rep


def find_lost_volumes(src, boot_offsets, known, cap=60) -> list[LostVolume]:
    """Boot sectors found by the scan that no partition table entry points to."""
    out, known, n = [], set(known), len(src)
    for off in sorted(boot_offsets):
        if off in known:
            continue
        fs = probe_fs(src, off, n)
        if not fs or not fs.size:
            continue
        known.update(fs.backups)
        hint = ""
        if fs.name == "NTFS" and off >= fs.size and src[off - fs.size + 3:off - fs.size + 11] != b"NTFS    ":
            hint = f"if this is a backup boot sector, the volume began at {hx(off - fs.size)}"
        out.append(LostVolume(off, fs.name, fs.size, hint))
        if len(out) >= cap:
            break
    return out
