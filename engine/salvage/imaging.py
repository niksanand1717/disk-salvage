"""Copy a drive to an image file, resumably, so recovery can work on the copy.

The image sits next to a small JSON map (<image>.map) that records how far the
copy got, which drive it came from and which areas could not be read. Running
the same copy again continues where it stopped; a map from another drive is
refused.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable

from salvage.binutil import MB, human
from salvage.errors import ImageMismatch, OutOfSpace
from salvage.events import Cancelled, CancelToken, EventSink, NullSink, Progress
from salvage.sources import image_map_path, read_image_map


def merge_ranges(ranges) -> list[list[int]]:
    """Sorted, non-overlapping [offset, length] list."""
    out: list[list[int]] = []
    for o, l in sorted(ranges):
        if out and o <= out[-1][0] + out[-1][1]:
            out[-1][1] = max(out[-1][1], o + l - out[-1][0])
        else:
            out.append([o, l])
    return out


@dataclass
class ImageReport:
    path: str
    size: int
    copied: int
    bad: list[tuple[int, int]] = field(default_factory=list)
    done: bool = False
    stopped: str = ""       # "", "cancelled", or an error message
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"path": self.path, "size": self.size, "copied": self.copied, "done": self.done,
                "bad": [list(x) for x in self.bad], "bad_bytes": sum(l for _, l in self.bad),
                "stopped": self.stopped, "seconds": self.seconds}


class Imager:
    """Sequential block copy of a source into an image file.

    Blocks are read with the source's own salvage logic when it has one
    (DeviceSource.load_block: bad sectors become zeros and are recorded),
    otherwise by plain slicing.
    """

    def __init__(self, src, dest: str, events: EventSink | None = None, cancel: CancelToken | None = None,
                 block: int = 4 * MB, reserve_bytes: int = 256 * MB, save_every: float = 5.0,
                 disk_usage: Callable = shutil.disk_usage, clock: Callable = time.monotonic):
        self.src, self.dest = src, dest
        self.events, self.cancel = events or NullSink(), cancel or CancelToken()
        self.block = getattr(src, "BLOCK", block)
        self.reserve, self.save_every = reserve_bytes, save_every
        self._disk_usage, self._clock = disk_usage, clock

    # -------------------------------------------------------------- the map
    def _identity(self) -> list | None:
        ident = getattr(self.src, "ident", None)
        return list(ident) if ident else None

    def _sig0(self) -> str:
        return bytes(self.src[0:min(512, len(self.src))]).hex()

    def _load_map(self) -> dict:
        size = len(self.src)
        m = read_image_map(self.dest)
        if m is None or not os.path.exists(self.dest):
            return {"source": self.src.path, "size": size, "ident": self._identity(),
                    "sig0": self._sig0(), "pos": 0, "bad": [], "done": False}
        if m.get("size") != size:
            raise ImageMismatch(f"{self.dest} is a copy of a {human(m.get('size'))} drive, "
                                f"but this one is {human(size)}; choose another image file")
        ident = self._identity()
        if m.get("ident") and ident and m["ident"] != ident:
            raise ImageMismatch(f"{self.dest} was copied from a different drive ({' '.join(m['ident'])})")
        if not (m.get("ident") and ident) and m.get("sig0") and m["sig0"] != self._sig0():
            raise ImageMismatch(f"{self.dest} does not start like this drive; it is probably another drive's copy")
        return m

    def _save_map(self, m: dict) -> None:
        path = image_map_path(self.dest)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(m, f)
        os.replace(tmp, path)

    # ----------------------------------------------------------------- copy
    def _read_block(self, off: int, ln: int) -> bytes:
        if hasattr(self.src, "load_block") and off % self.block == 0:
            return self.src.load_block(off // self.block)
        return bytes(self.src[off:off + ln])

    def _check_space(self, remaining: int, f) -> None:
        free = self._disk_usage(os.path.dirname(os.path.abspath(self.dest)) or ".").free
        if free - remaining < self.reserve:
            raise OutOfSpace(f"only {human(free)} free for the image; {human(remaining)} still to copy "
                             f"(keeping {human(self.reserve)} spare)")

    def run(self) -> ImageReport:
        t0 = self._clock()
        size = len(self.src)
        m = self._load_map()
        rep = ImageReport(self.dest, size, m["pos"])
        if m.get("done"):
            rep.done, rep.bad = True, [tuple(x) for x in m["bad"]]
            return rep
        if m["pos"]:
            self.events.emit("log", message=f"resuming the copy at {human(m['pos'])} of {human(size)}")
        os.makedirs(os.path.dirname(os.path.abspath(self.dest)), exist_ok=True)
        mode = "r+b" if os.path.exists(self.dest) else "w+b"
        prog = Progress(self.events, "imaging", size)
        try:
            with open(self.dest, mode) as f:
                current = f.seek(0, os.SEEK_END)
                self._check_space(size - min(current, size), f)
                if current < size:
                    f.truncate(size)                    # unread areas stay zero
                self._save_map(m)
                last_save = self._clock()
                pos, prior_bad = m["pos"], [tuple(x) for x in m["bad"]]
                while pos < size:
                    self.cancel.check()
                    ln = min(self.block, size - pos)
                    data = self._read_block(pos, ln)
                    f.seek(pos)
                    f.write(data)
                    pos += ln
                    m["pos"] = pos
                    m["bad"] = merge_ranges(prior_bad + list(self.src.bad_ranges()))
                    prog.update(pos, bad=sum(l for _, l in m["bad"]))
                    if self._clock() - last_save >= self.save_every:
                        f.flush()
                        self._save_map(m)
                        last_save = self._clock()
                f.flush()
                os.fsync(f.fileno())
            m["done"] = True
            prog.update(size, force=True, bad=sum(l for _, l in m["bad"]))
        except Cancelled:
            rep.stopped = "cancelled"
        except OutOfSpace as ex:
            rep.stopped = str(ex)
            self.events.emit("warning", message=str(ex))
        finally:
            self._save_map(m)
        rep.copied, rep.done = m["pos"], m["done"]
        rep.bad = [tuple(x) for x in m["bad"]]
        rep.seconds = self._clock() - t0
        return rep
