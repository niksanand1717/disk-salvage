"""Progress / event reporting and cancellation.

Engine code never prints: it emits events to an EventSink. The CLI plugs in a
ConsoleSink, the UI server a JsonLinesSink, tests a CollectingSink.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, Protocol, TextIO

from salvage.binutil import GB, MB


class EventSink(Protocol):
    def emit(self, kind: str, **data: Any) -> None: ...


class NullSink:
    def emit(self, kind: str, **data: Any) -> None:
        pass


class CollectingSink:
    """Keeps every event in memory (tests)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind: str, **data: Any) -> None:
        self.events.append((kind, data))

    def of(self, kind: str) -> list[dict]:
        return [d for k, d in self.events if k == kind]


class JsonLinesSink:
    """One JSON object per line; the UI protocol."""

    def __init__(self, stream: TextIO, job: Any = None, lock: threading.Lock | None = None):
        self.stream, self.job = stream, job
        self.lock = lock or threading.Lock()

    def emit(self, kind: str, **data: Any) -> None:
        msg = {"event": kind, "data": data}
        if self.job is not None:
            msg["job"] = self.job
        line = json.dumps(msg, default=str)
        with self.lock:
            self.stream.write(line + "\n")
            self.stream.flush()


class ConsoleSink:
    """Human-readable output for the command line."""

    def __init__(self, stream: TextIO = sys.stdout):
        self.stream = stream
        self._inline = False

    def _line(self, text: str) -> None:
        if self._inline:
            self.stream.write("\n")
            self._inline = False
        self.stream.write(text + "\n")
        self.stream.flush()

    def emit(self, kind: str, **d: Any) -> None:
        if kind == "progress":
            self.stream.write("\r  " + format_progress(d) + "   ")
            self.stream.flush()
            self._inline = True
        elif kind == "log":
            self._line(d.get("message", ""))
        elif kind == "warning":
            self._line("  !! " + d.get("message", ""))
        elif kind == "drive_lost":
            self._line(f"  !! drive stopped responding at {d['offset'] / GB:.2f} GB - waiting for it."
                       "\n     Unplug it, wait a few seconds, plug it in again. Ctrl+C stops.")
        elif kind == "drive_back":
            self._line(f"     drive is back ({d['path']}) - continuing")
        elif kind == "drive_waiting":
            self.stream.write(f"\r     waiting for the drive... {d['seconds']}s   ")
            self.stream.flush()
            self._inline = True
        elif kind == "phase":
            self._line(f"{d['name']}...")


def format_progress(d: dict) -> str:
    phase, done, total = d.get("phase", ""), d.get("done", 0), d.get("total", 0)
    if d.get("unit") == "bytes":
        text = f"{phase}: {done / GB:7.2f} / {total / GB:.2f} GB"
        if d.get("rate"):
            text += f"  {d['rate'] / MB:6.1f} MB/s"
    else:
        text = f"{phase}: {done}/{total}"
    if d.get("eta") is not None:
        eta = int(d["eta"])
        text += f"  ETA {eta // 60:3d}m{eta % 60:02d}s"
    for k in ("candidates", "saved", "skipped"):
        if k in d:
            text += f"  {k}: {d[k]}"
    return text


class Progress:
    """Throttled progress reporting with rate and ETA."""

    def __init__(self, sink: EventSink, phase: str, total: int, unit: str = "bytes",
                 interval: float = 0.25, clock=time.monotonic):
        self.sink, self.phase, self.total, self.unit = sink, phase, total, unit
        self.interval, self.clock = interval, clock
        self.t0 = clock()
        self._last = -1e9
        self._start_done: int | None = None

    def update(self, done: int, force: bool = False, **extra: Any) -> None:
        now = self.clock()
        if self._start_done is None:
            self._start_done = done
        if not force and now - self._last < self.interval:
            return
        self._last = now
        el = max(now - self.t0, 1e-6)
        rate = (done - self._start_done) / el
        eta = (self.total - done) / rate if rate > 0 else None
        self.sink.emit("progress", phase=self.phase, done=done, total=self.total,
                       unit=self.unit, rate=rate if self.unit == "bytes" else None,
                       eta=eta, **extra)


class Cancelled(Exception):
    """The job was cancelled by the user."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()
