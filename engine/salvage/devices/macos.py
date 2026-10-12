from __future__ import annotations

import os
import plistlib
import re
import subprocess

from salvage.devices.base import DriveInfo, Platform
from salvage.errors import AccessDenied

DKIOCGETBLOCKSIZE = 0x40046418
DKIOCGETBLOCKCOUNT = 0x40086419


def _diskutil_info(target):
    try:
        out = subprocess.run(["diskutil", "info", "-plist", target], capture_output=True,
                             timeout=15, check=True).stdout
        return plistlib.loads(out)
    except Exception:
        return {}


def _whole(path):
    """/dev/rdisk4 -> disk4"""
    m = re.search(r"r?(disk\d+)$", path)
    return m.group(1) if m else None


class MacPlatform(Platform):
    def is_device_path(self, path):
        return path.startswith("/dev/")

    def device_size(self, f):
        import fcntl
        import struct
        try:
            bs = struct.unpack("I", fcntl.ioctl(f.fileno(), DKIOCGETBLOCKSIZE, b"\0" * 4))[0]
            bc = struct.unpack("Q", fcntl.ioctl(f.fileno(), DKIOCGETBLOCKCOUNT, b"\0" * 8))[0]
            return bs * bc or None
        except OSError:
            try:
                size = os.lseek(f.fileno(), 0, os.SEEK_END)
                os.lseek(f.fileno(), 0, os.SEEK_SET)
                return size or None
            except OSError:
                return None

    def _disks(self):
        return sorted((n for n in os.listdir("/dev") if re.fullmatch(r"disk\d+", n)),
                      key=lambda n: int(n[4:]))

    def list_drives(self):
        out = []
        for n in self._disks():
            info = _diskutil_info(n)
            size = info.get("TotalSize") or info.get("Size")
            out.append(DriveInfo(path=f"/dev/r{n}", size=size, model=info.get("MediaName", ""),
                                 serial="", removable=info.get("RemovableMedia", info.get("Removable")),
                                 bus=info.get("BusProtocol", ""), note="" if size else "no media"))
        if out and not any(os.access(d.path, os.R_OK) for d in out):
            raise AccessDenied("reading drives needs root (run with sudo)")
        return out

    def identity(self, f, path):
        name = _whole(path)
        info = _diskutil_info(name) if name else {}
        return (info.get("MediaName", ""), info.get("TotalSize")) if info else None

    def candidate_paths(self, path):
        raw = path.startswith("/dev/r")
        return [path] + [f"/dev/{'r' if raw else ''}{n}" for n in self._disks()
                         if f"/dev/{'r' if raw else ''}{n}" != path]

    def disk_of_path(self, path):
        p = os.path.abspath(path)
        while not os.path.ismount(p) and p != os.path.dirname(p):
            p = os.path.dirname(p)
        info = _diskutil_info(p)
        parent = info.get("ParentWholeDisk")
        return f"/dev/{parent}" if parent else None

    def same_disk(self, a, b):
        return _whole(a) is not None and _whole(a) == _whole(b)
