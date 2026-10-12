"""Real-time carving: files are saved while the scan is still running.

The scan hands over signature hits chunk by chunk. Each candidate is parsed and saved as
soon as the next candidate is known (parsers may use its position as an upper bound), so
results are identical to scanning everything first. If the drive fails or the job stops,
every file found up to that point is already on disk and, via the checkpoint callback,
in the report.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from salvage.binutil import MB
from salvage.carving.scanner import Scanner
from salvage.carving.writer import OutputWriter
from salvage.errors import OutOfSpace
from salvage.events import Cancelled, CancelToken, EventSink, NullSink, Progress
from salvage.formats.base import FormatRegistry, Signature
from salvage.manifest import FileRecord
from salvage.sources import overlaps

MARKER = "boot"      # kind used for boot-sector hits (reported, never carved)


@dataclass
class CarveOptions:
    align: int = 512
    min_size: int = 2048
    overlap: bool = False
    scan_chunk: int = 256 * MB      # smaller (e.g. 32 MB) for slow drives: more frequent progress
    checkpoint_every: float = 5.0   # seconds between checkpoint() calls (report.json updates)


@dataclass
class CarveReport:
    files: list[FileRecord] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    candidates: int = 0
    boot_offsets: list[int] = field(default_factory=list)
    stopped: str = ""        # "", "cancelled", or an error message (e.g. out of space)
    seconds: float = 0.0


class Carver:
    def __init__(self, src, registry: FormatRegistry, writer: OutputWriter,
                 events: EventSink | None = None, cancel: CancelToken | None = None,
                 options: CarveOptions | None = None, markers: list[Signature] | None = None,
                 checkpoint: Callable[[list[FileRecord]], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.src, self.registry, self.writer = src, registry, writer
        self.events, self.cancel = events or NullSink(), cancel or CancelToken()
        self.opt = options or CarveOptions()
        self.markers = markers or []
        self.checkpoint, self.clock = checkpoint, clock
        self.report = CarveReport()          # live; still readable if run() raises

    def run(self, wanted: set[str]) -> CarveReport:
        t0 = self.clock()
        rep = self.report = CarveReport()
        parsers = self.registry.select(wanted)
        sigs = [(s, p.kind) for p in parsers for s in p.signatures]
        sigs += [(s, MARKER) for s in self.markers]
        try:
            self.events.emit("phase", name="recovering")
            self._stream(sigs, wanted, rep)
        except Cancelled:
            rep.stopped = "cancelled"
        except OutOfSpace as ex:
            rep.stopped = str(ex)
            self.events.emit("warning", message=str(ex))
        rep.seconds = self.clock() - t0
        return rep

    # ----------------------------------------------------------------- stream
    def _stream(self, sigs, wanted, rep):
        n = len(self.src)
        scanner = Scanner(self.src, self.opt.align, self.opt.scan_chunk, self.events, self.cancel)
        prog = Progress(self.events, "recovering", n)
        pending: deque[tuple[int, str]] = deque()       # candidates in offset order
        self._covered = 0
        self._last_cp = self.clock()

        def tick(done, force=False):
            prog.update(done, force=force, candidates=rep.candidates, saved=len(rep.files))

        try:
            for done, hits in scanner.chunks(sigs):
                for off, kind in hits:
                    if kind == MARKER:
                        rep.boot_offsets.append(off)
                    else:
                        pending.append((off, kind))
                        rep.candidates += 1
                while len(pending) > 1:                # the last one waits for its successor
                    start, kind = pending.popleft()
                    self._carve_one(start, kind, pending[0][0], wanted, rep)
                    tick(done)
                tick(done)
                self._maybe_checkpoint(rep)
        except (Cancelled, OutOfSpace):
            raise
        except Exception:
            self._salvage_pending(pending, wanted, rep)    # the scan died: save what is already found
            raise
        while pending:
            start, kind = pending.popleft()
            self._carve_one(start, kind, pending[0][0] if pending else n, wanted, rep)
        tick(n, force=True)
        self._maybe_checkpoint(rep, force=True)

    def _salvage_pending(self, pending, wanted, rep):
        """Best effort after a failed scan: candidates found but not yet saved."""
        n = len(self.src)
        while pending:
            start, kind = pending.popleft()
            try:
                self._carve_one(start, kind, pending[0][0] if pending else n, wanted, rep)
            except Exception:  # noqa: BLE001 - the source is failing; skip what cannot be read
                continue

    def _maybe_checkpoint(self, rep, force=False):
        if self.checkpoint and (force or self.clock() - self._last_cp >= self.opt.checkpoint_every):
            self.checkpoint(rep.files)
            self._last_cp = self.clock()

    def _carve_one(self, start, kind, nxt, wanted, rep):
        self.cancel.check()
        if not self.opt.overlap and start < self._covered:
            return
        n = len(self.src)
        try:
            res = self.registry.get(kind).parse(self.src, start, n, nxt)
        except (IndexError, ValueError, OverflowError):
            res = None
        if not res or res.end - start < self.opt.min_size or res.ext not in wanted:
            return
        status = res.status
        if status == "ok" and overlaps(self.src.bad_ranges(), start, res.end):
            status = "badsectors"
        idx = len(rep.files) + 1
        rel, digest = self.writer.save(self.src, start, res.end, res.ext, status, idx)
        if status == "ok" and overlaps(self.src.bad_ranges(), start, res.end):
            status = "badsectors"                       # found unreadable while copying it
            retag = getattr(self.writer, "retag", None)
            if retag and rel:
                rel = retag(rel, start, res.ext, status, idx)
        rec = FileRecord(idx, start, res.end - start, res.ext, status, digest, rel)
        rep.files.append(rec)
        rep.stats[res.ext] = rep.stats.get(res.ext, 0) + 1
        self._covered = max(self._covered, res.end)
        self.events.emit("file", **rec.to_dict())
