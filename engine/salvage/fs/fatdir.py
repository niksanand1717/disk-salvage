"""Find surviving FAT folder listings anywhere in a volume's data area.

Even when the FAT and the root folder are wiped, sub-folders are ordinary data
clusters and often survive. Each entry still holds the file's name, size and
first cluster, which is enough to give carved files back their names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from salvage.binutil import MB
from salvage.events import CancelToken, EventSink, NullSink, Progress


@dataclass(frozen=True)
class DirEntry:
    name: str
    size: int
    offset: int          # where the file's first cluster starts on the source
    deleted: bool
    is_dir: bool


def _lfn_part(e: bytes) -> str:
    return (e[1:11] + e[14:26] + e[28:32]).decode("utf-16-le", "ignore").split("\0")[0].replace("￿", "")


def parse_dir_cluster(c: bytes, data_start: int, cluster: int) -> list[DirEntry]:
    out, lfn = [], []
    for i in range(0, len(c) - 31, 32):
        e = c[i:i + 32]
        if e[0] == 0:
            break
        if e[11] == 0x0F:
            lfn.insert(0, _lfn_part(e))
            continue
        name, lfn = "".join(lfn), []
        if e[0] == 0x2E or e[11] & 0x08:            # "." / ".." / volume label
            continue
        if not name:
            base = e[:8].decode("latin1").strip()
            ext = e[8:11].decode("latin1").strip()
            name = base + ("." + ext if ext else "")
        clus = int.from_bytes(e[20:22], "little") << 16 | int.from_bytes(e[26:28], "little")
        if clus < 2:
            continue
        out.append(DirEntry(name, int.from_bytes(e[28:32], "little"), data_start + (clus - 2) * cluster,
                            e[0] == 0xE5, bool(e[11] & 0x10)))
    return out


def is_dir_cluster(c: bytes) -> bool:
    return c[:11] == b".          " and bool(c[11] & 0x10)


def scan_fat_dirs(src, data_start: int, cluster: int, end: int | None = None,
                  events: EventSink | None = None, cancel: CancelToken | None = None) -> Iterator[DirEntry]:
    """Every entry of every folder cluster between data_start and end."""
    end = min(len(src), end or len(src))
    events, cancel = events or NullSink(), cancel or CancelToken()
    prog = Progress(events, "finding folder listings", end - data_start)
    chunk = max(cluster, (64 * MB // cluster) * cluster)
    o = data_start
    while o < end:
        cancel.check()
        buf = src[o:min(end, o + chunk)]
        for k in range(0, len(buf) - cluster + 1, cluster):
            c = buf[k:k + cluster]
            if is_dir_cluster(c):
                yield from parse_dir_cluster(c, data_start, cluster)
        o += len(buf)
        prog.update(o - data_start)
