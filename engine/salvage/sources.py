"""Read-only byte sources: an image file, a raw device, or memory (tests).

Everything that carves or analyses works against the small ByteSource
protocol, so the three are interchangeable.
"""
from __future__ import annotations

import json
import mmap
import os
import threading
import time
from collections import OrderedDict
from typing import Callable, Protocol

from salvage.binutil import MB
from salvage.devices import Platform, get_platform
from salvage.errors import DriveDropped, ReadTimeout, SourceUnavailable
from salvage.events import CancelToken, EventSink, NullSink


class ByteSource(Protocol):
    path: str

    def __len__(self) -> int: ...
    def __getitem__(self, k): ...              # int -> int, slice -> bytes
    def find(self, sub: bytes, start: int = 0, end: int | None = None) -> int: ...
    def bad_ranges(self) -> list[tuple[int, int]]: ...
    def close(self) -> None: ...


def overlaps(ranges, start, end) -> bool:
    return any(o < end and start < o + ln for o, ln in ranges)


class MemorySource:
    def __init__(self, data: bytes, path: str = "<memory>", bad=None):
        self.data, self.path, self._bad = bytes(data), path, list(bad or [])

    def __len__(self):
        return len(self.data)

    def __getitem__(self, k):
        return self.data[k]

    def find(self, sub, start=0, end=None):
        return self.data.find(sub, start, len(self.data) if end is None else end)

    def bad_ranges(self):
        return self._bad

    def close(self):
        pass


def image_map_path(image_path: str) -> str:
    return image_path + ".map"


def read_image_map(image_path: str) -> dict | None:
    try:
        with open(image_map_path(image_path)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class FileSource:
    """An image file, memory-mapped read-only."""

    def __init__(self, path: str):
        self.path = path
        self._f = open(path, "rb")
        size = os.fstat(self._f.fileno()).st_size
        self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ) if size else b""
        self.map_info = read_image_map(path)
        self._bad = [tuple(x) for x in (self.map_info or {}).get("bad", [])]

    @property
    def incomplete(self) -> bool:
        return bool(self.map_info) and not self.map_info.get("done", False)

    def __len__(self):
        return len(self._mm)

    def __getitem__(self, k):
        return self._mm[k]

    def find(self, sub, start=0, end=None):
        return self._mm.find(sub, max(0, start), len(self._mm) if end is None else end)

    def bad_ranges(self):
        return self._bad

    def close(self):
        if isinstance(self._mm, mmap.mmap):
            self._mm.close()
        self._f.close()


class DeviceSource:
    """Read-only, mmap-like view of a raw device.

    * reads are block-aligned (raw disks require it) and cached;
    * a bad sector reads as zeros and is listed in bad_ranges();
    * if the drive disconnects, reads pause until the same drive is back;
    * a read the drive never answers times out and the handle is reopened;
    * an area where the drive keeps dropping out is skipped (zeros, listed).
    """

    BLOCK = 4 * MB

    def __init__(self, path: str, platform: Platform | None = None, events: EventSink | None = None,
                 cancel: CancelToken | None = None, read_timeout: float | None = 30.0,
                 max_drops: int = 3, poll_interval: float = 2.0, cache_blocks: int = 64,
                 opener: Callable | None = None, sleep: Callable = time.sleep):
        self.path = path
        self.platform = platform or get_platform()
        self.events = events or NullSink()
        self.cancel = cancel or CancelToken()
        self.read_timeout, self.max_drops, self.poll_interval = read_timeout, max_drops, poll_interval
        self._open = opener or self.platform.open_device
        self._sleep = sleep
        self.f = self._open(path)
        self.size = self.platform.device_size(self.f)
        if not self.size:
            self.f.close()
            raise SourceUnavailable(f"{path}: drive reports no size (no media / unreadable)")
        self.ident = self.platform.identity(self.f, path)
        try:
            self.sig0 = self._read_once(0, 512)
        except OSError:
            self.sig0 = None
        self.cache: OrderedDict[int, bytes] = OrderedDict()
        self.cache_blocks = cache_blocks
        self.bad: list[list[int]] = []
        self.drops: dict[int, int] = {}
        self._lbi, self._lblk = -1, b""

    # ---------------------------------------------------------------- basics
    def __len__(self):
        return self.size

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass

    def bad_ranges(self):
        return [tuple(x) for x in self.bad]

    # ------------------------------------------------------------- low level
    def _read_once(self, off, ln, f=None):
        f = f or self.f
        f.seek(off)
        out = bytearray()
        while len(out) < ln:
            chunk = f.read(ln - len(out))
            if not chunk:
                break
            out += chunk
        if len(out) < ln:
            raise OSError("short read")
        return bytes(out)

    def _timed_read(self, off, ln):
        if not self.read_timeout:
            return self._read_once(off, ln)
        box: dict = {}
        f = self.f              # a hung reader must never touch a handle opened later

        def run():
            try:
                box["v"] = self._read_once(off, ln, f)
            except BaseException as ex:  # noqa: BLE001 - re-raised in the caller
                box["e"] = ex
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(self.read_timeout)
        if t.is_alive():
            raise ReadTimeout(f"no answer within {self.read_timeout:.0f}s")
        if "e" in box:
            raise box["e"]
        return box["v"]

    def pread(self, off: int, ln: int) -> bytes:
        """Read exactly ln bytes or raise OSError (bad area) / DriveDropped."""
        while True:
            self.cancel.check()
            try:
                return self._timed_read(off, ln)
            except ReadTimeout:
                hung = True
                self.events.emit("warning", message=f"drive did not answer at offset {off:#x}; reopening it")
            except OSError as ex:
                if not self.platform.is_disconnect(self.f, self.path, ex, self.size):
                    raise                               # a bad sector, not a disconnect
                hung = False
            bi = off // self.BLOCK
            self.drops[bi] = self.drops.get(bi, 0) + 1
            if self.drops[bi] > self.max_drops:
                raise DriveDropped(f"drive keeps failing at offset {off:#x}")
            if not (hung and self._reopen()):
                self._wait_for_drive(off)

    def _try_open(self, p):
        try:
            f = self._open(p)
        except OSError:
            return None
        try:
            if self.platform.device_size(f) == self.size:
                if self.ident is None or self.platform.identity(f, p) == self.ident:
                    return f
                f.seek(0)
                if self.sig0 and f.read(512) == self.sig0:
                    return f
        except Exception:  # noqa: BLE001 - any failure means "not our drive"
            pass
        f.close()
        return None

    def _reopen(self) -> bool:
        self.close()
        f = self._try_open(self.path)
        if f:
            self.f = f
            return True
        return False

    def _wait_for_drive(self, off):
        self.events.emit("drive_lost", offset=off)
        self.close()
        t0 = time.monotonic()
        while True:
            self.cancel.check()
            self._sleep(self.poll_interval)
            for p in self.platform.candidate_paths(self.path):
                f = self._try_open(p)
                if f:
                    self.f, self.path = f, p
                    self.events.emit("drive_back", path=p)
                    return
            self.events.emit("drive_waiting", seconds=int(time.monotonic() - t0))

    def _mark_bad(self, off, ln):
        merged: list[list[int]] = []
        for o, l in sorted(self.bad + [[off, ln]]):
            if merged and o <= merged[-1][0] + merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], o + l - merged[-1][0])
            else:
                merged.append([o, l])
        self.bad = merged

    def load_block(self, bi: int) -> bytes:
        """One BLOCK, salvaging what can be read; unreadable parts become zeros."""
        off = bi * self.BLOCK
        ln = min(self.BLOCK, self.size - off)
        try:
            try:
                return self.pread(off, ln)
            except DriveDropped:
                raise
            except OSError:
                pass
            out = bytearray(ln)                         # salvage: 4K units, then 512-byte sectors
            for p in range(0, ln, 4096):
                u = min(4096, ln - p)
                try:
                    out[p:p + u] = self.pread(off + p, u)
                    continue
                except DriveDropped:
                    raise
                except OSError:
                    pass
                for q in range(p, p + u, 512):
                    try:
                        out[q:q + 512] = self.pread(off + q, min(512, ln - q))
                    except DriveDropped:
                        raise
                    except OSError:
                        self._mark_bad(off + q, min(512, ln - q))
            return bytes(out)
        except DriveDropped as ex:
            self.events.emit("warning", message=f"{ex} - skipping {ln // MB} MB (read as zeros)")
            self._mark_bad(off, ln)
            return bytes(ln)

    def _block(self, bi):
        if bi == self._lbi:
            return self._lblk
        blk = self.cache.get(bi)
        if blk is None:
            blk = self.load_block(bi)
            self.cache[bi] = blk
            if len(self.cache) > self.cache_blocks:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(bi)
        self._lbi, self._lblk = bi, blk
        return blk

    # ------------------------------------------------------- mmap-like access
    def __getitem__(self, k):
        if isinstance(k, slice):
            a, b, st = k.indices(self.size)
            if st != 1:
                raise ValueError("step not supported")
            if b <= a:
                return b""
            ba, bb = a // self.BLOCK, (b - 1) // self.BLOCK
            if ba == bb:
                o = ba * self.BLOCK
                return self._block(ba)[a - o:b - o]
            parts = []
            for bi in range(ba, bb + 1):
                # cached even for big reads: real-time carving saves files from the area just
                # scanned, so it is served from memory instead of being read from the drive again
                blk = self._block(bi)
                o = bi * self.BLOCK
                parts.append(blk[max(a, o) - o:min(b, o + len(blk)) - o])
            return b"".join(parts)
        if k < 0:
            k += self.size
        if not 0 <= k < self.size:
            raise IndexError(k)
        bi = k // self.BLOCK
        return self._block(bi)[k - bi * self.BLOCK]

    def find(self, sub, start=0, end=None):
        end = self.size if end is None else min(end, self.size)
        L, pos = len(sub), max(0, start)
        while pos + L <= end:
            bi, bo = divmod(pos, self.BLOCK)
            base = bi * self.BLOCK
            blk = self._block(bi)
            i = blk.find(sub, bo, min(len(blk), end - base))
            if i != -1:
                return base + i
            nb = base + self.BLOCK
            if L > 1 and nb < end:                      # match straddling two blocks
                s0 = max(pos, nb - L + 1)
                j = self[s0:min(end, nb + L - 1)].find(sub)
                if j != -1:
                    return s0 + j
            pos = nb
        return -1


def open_source(path: str, platform: Platform | None = None, events: EventSink | None = None,
                cancel: CancelToken | None = None, raw: bool = False, read_timeout: float | None = 30.0):
    """A DeviceSource for drives (or when raw=True), else a FileSource."""
    platform = platform or get_platform()
    try:
        if raw or platform.is_device_path(path):
            return DeviceSource(path, platform, events, cancel, read_timeout=read_timeout)
        return FileSource(path)
    except PermissionError as ex:
        from salvage.errors import AccessDenied
        raise AccessDenied("reading a drive needs Administrator / root rights") from ex
    except FileNotFoundError as ex:
        raise SourceUnavailable(f"{path}: not found") from ex
