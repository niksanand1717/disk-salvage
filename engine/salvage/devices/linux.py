from __future__ import annotations

import errno
import os

from salvage.devices.base import DriveInfo, Platform
from salvage.errors import AccessDenied

SKIP_PREFIXES = ("loop", "ram", "zram", "dm-", "sr", "fd")


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


class LinuxPlatform(Platform):
    sys_block = "/sys/block"

    def is_device_path(self, path):
        return path.startswith("/dev/")

    def device_size(self, f):
        try:
            size = os.lseek(f.fileno(), 0, os.SEEK_END)
            os.lseek(f.fileno(), 0, os.SEEK_SET)
            return size or None
        except OSError:
            return None

    def _disks(self):
        try:
            names = sorted(os.listdir(self.sys_block))
        except OSError:
            return []
        return [n for n in names if not n.startswith(SKIP_PREFIXES)]

    def _info(self, name):
        base = os.path.join(self.sys_block, name)
        size = int(_read(os.path.join(base, "size"), "0") or 0) * 512
        model = " ".join(x for x in (_read(f"{base}/device/vendor"), _read(f"{base}/device/model")) if x)
        serial = _read(f"{base}/device/serial") or _read(f"{base}/device/wwid")
        removable = _read(f"{base}/removable") == "1"
        real = os.path.realpath(base)
        bus = "USB" if "/usb" in real else "NVMe" if name.startswith("nvme") else \
              "MMC" if name.startswith("mmcblk") else ""
        return DriveInfo(path=f"/dev/{name}", size=size or None, model=model, serial=serial,
                         removable=removable, bus=bus, note="" if size else "no media")

    def list_drives(self):
        drives = [self._info(n) for n in self._disks()]
        if drives and not any(os.access(d.path, os.R_OK) for d in drives):
            raise AccessDenied("reading drives needs root (run with sudo)")
        return drives

    def identity(self, f, path):
        name = os.path.basename(path)
        info = self._info(name)
        return (info.model, info.serial) if (info.model or info.serial) else None

    def is_disconnect(self, f, path, ex, expected_size):
        return ex.errno in (errno.ENODEV, errno.ENXIO) or not os.path.exists(path)

    def candidate_paths(self, path):
        return [path] + [f"/dev/{n}" for n in self._disks() if f"/dev/{n}" != path]

    def disk_of_path(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        link = f"/sys/dev/block/{os.major(st.st_dev)}:{os.minor(st.st_dev)}"
        real = os.path.realpath(link)
        if not os.path.exists(real):
            return None
        if os.path.exists(os.path.join(real, "partition")):
            real = os.path.dirname(real)
        return f"/dev/{os.path.basename(real)}"
