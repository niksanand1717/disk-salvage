"""Where carved bytes go: a folder (with free-space guard) or nowhere (dry run)."""
from __future__ import annotations

import hashlib
import os
import shutil
from typing import Callable, Protocol

from salvage.binutil import MB, human
from salvage.errors import OutOfSpace


class OutputWriter(Protocol):
    def save(self, src, start: int, end: int, ext: str, status: str, idx: int) -> tuple[str, str]:
        """Store bytes [start, end) of src. Returns (relative path, sha256)."""


class DryRunWriter:
    def save(self, src, start, end, ext, status, idx):
        return "", ""


def copy_range(src, start, end, path, chunk=16 * MB) -> str:
    """Copy a byte range to path, returning its sha256. Written as .part, renamed at the end."""
    h = hashlib.sha256()
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        p = start
        while p < end:
            q = min(end, p + chunk)
            buf = src[p:q]
            f.write(buf)
            h.update(buf)
            p = q
    os.replace(tmp, path)
    return h.hexdigest()


class FolderWriter:
    """Saves files as <out>/<ext>/<idx>_0x<offset>[_status].<ext>."""

    def __init__(self, out_dir: str, reserve_bytes: int = 256 * MB,
                 disk_usage: Callable = shutil.disk_usage):
        self.out_dir, self.reserve = out_dir, reserve_bytes
        self._disk_usage = disk_usage
        os.makedirs(out_dir, exist_ok=True)

    def free_bytes(self) -> int:
        return self._disk_usage(self.out_dir).free

    def save(self, src, start, end, ext, status, idx):
        need = end - start
        free = self.free_bytes()
        if free - need < self.reserve:
            raise OutOfSpace(f"only {human(free)} free in {self.out_dir}; the next file needs "
                             f"{human(need)} (keeping {human(self.reserve)} spare)")
        folder = os.path.join(self.out_dir, ext)
        os.makedirs(folder, exist_ok=True)
        tag = "" if status == "ok" else f"_{status}"
        rel = os.path.join(ext, f"{idx:06d}_0x{start:x}{tag}.{ext}")
        digest = copy_range(src, start, end, os.path.join(self.out_dir, rel))
        return rel.replace(os.sep, "/"), digest
