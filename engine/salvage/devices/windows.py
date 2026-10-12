from __future__ import annotations

import os
import re

from salvage.binutil import u32
from salvage.devices.base import DriveInfo, Platform
from salvage.errors import AccessDenied

GONE_WINERR = {2, 3, 6, 21, 55, 433, 1167}  # not found, bad handle, not ready, gone, no device
IOCTL_DISK_GET_LENGTH_INFO = 0x7405C
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x700A0
IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080
BUS_TYPES = {7: "USB", 8: "RAID", 11: "SATA", 12: "SD", 13: "MMC", 17: "NVMe", 1: "SCSI", 3: "ATA"}


def _k32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return k32


def _ioctl_handle(h, code, inbuf=b"", outsize=256):
    import ctypes
    from ctypes import wintypes
    k32 = _k32()
    ib = ctypes.create_string_buffer(inbuf, len(inbuf)) if inbuf else None
    out, got = ctypes.create_string_buffer(outsize), wintypes.DWORD(0)
    if not k32.DeviceIoControl(h, code, ib, len(inbuf), out, outsize, ctypes.byref(got), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return out.raw[:got.value]


def _ioctl(f, code, inbuf=b"", outsize=256):
    import msvcrt
    return _ioctl_handle(msvcrt.get_osfhandle(f.fileno()), code, inbuf, outsize)


def _query_handle(path):
    """Open a device with no read/write rights: enough for ioctls, no elevation needed."""
    k32 = _k32()
    h = k32.CreateFileW(path, 0, 3, None, 3, 0, None)    # share read|write, OPEN_EXISTING
    if h in (None, 0, -1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF):
        return None
    return h


class WindowsPlatform(Platform):
    def is_device_path(self, path):
        return path.startswith("\\\\.\\")

    def device_size(self, f):
        for code, at in ((IOCTL_DISK_GET_LENGTH_INFO, 0), (IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, 24)):
            try:
                val = int.from_bytes(_ioctl(f, code)[at:at + 8], "little")
                if val > 0:
                    return val
            except OSError:
                pass
        try:
            size = f.seek(0, os.SEEK_END)
            f.seek(0)
            return size or None
        except OSError:
            return None

    def _describe(self, f):
        try:
            d = _ioctl(f, IOCTL_STORAGE_QUERY_PROPERTY, bytes(12), 1024)
        except Exception:
            return None

        def s(at):
            o = u32(d, at, "little")
            if not o or o >= len(d):
                return ""
            e = d.find(b"\0", o)
            return d[o:e if e != -1 else len(d)].decode("latin1").strip()
        return {"vendor": s(12), "product": s(16), "serial": s(24),
                "removable": bool(d[10]), "bus": BUS_TYPES.get(u32(d, 28, "little"), "")}

    def identity(self, f, path):
        d = self._describe(f)
        return (d["vendor"], d["product"], d["serial"]) if d else None

    def is_disconnect(self, f, path, ex, expected_size):
        if getattr(ex, "winerror", None) in GONE_WINERR:
            return True
        try:
            return self.device_size(f) != expected_size
        except Exception:
            return True

    def candidate_paths(self, path):
        if path.lower().startswith("\\\\.\\physicaldrive"):
            others = [rf"\\.\PhysicalDrive{i}" for i in range(32)]
            return [path] + [p for p in others if p.lower() != path.lower()]
        return [path]

    def list_drives(self):
        out = []
        for i in range(32):
            p = rf"\\.\PhysicalDrive{i}"
            try:
                f = self.open_device(p)
            except PermissionError as ex:
                raise AccessDenied("reading drives needs Administrator rights") from ex
            except OSError:
                continue
            with f:
                d = self._describe(f) or {}
                size = self.device_size(f)
                out.append(DriveInfo(path=p, size=size,
                                     model=" ".join(x for x in (d.get("vendor"), d.get("product")) if x),
                                     serial=d.get("serial", ""), removable=d.get("removable"),
                                     bus=d.get("bus", ""), note="" if size else "no media"))
        return out

    def disk_of_path(self, path):
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not re.fullmatch(r"[A-Za-z]:", drive):
            return None
        h = _query_handle(rf"\\.\{drive}")
        if h is None:
            return None
        try:
            d = _ioctl_handle(h, IOCTL_STORAGE_GET_DEVICE_NUMBER, outsize=12)
            return rf"\\.\PhysicalDrive{u32(d, 4, 'little')}"
        except OSError:
            return None
        finally:
            _k32().CloseHandle(h)

    def same_disk(self, a, b):
        return a.lower() == b.lower()
