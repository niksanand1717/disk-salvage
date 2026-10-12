"""Scan for candidates, let each format's parser find the exact end, save the result."""
from __future__ import annotations

import bisect
import time
from dataclasses import dataclass, field

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
                 options: CarveOptions | None = None, markers: list[Signature] | None = None):
        self.src, self.registry, self.writer = src, registry, writer
        self.events, self.cancel = events or NullSink(), cancel or CancelToken()
        self.opt = options or CarveOptions()
        self.markers = markers or []

    def run(self, wanted: set[str]) -> CarveReport:
        t0 = time.monotonic()
        rep = CarveReport()
        parsers = self.registry.select(wanted)
        sigs = [(s, p.kind) for p in parsers for s in p.signatures]
        sigs += [(s, MARKER) for s in self.markers]
        try:
            self.events.emit("phase", name="scanning")
            scanner = Scanner(self.src, self.opt.align, self.opt.scan_chunk, self.events, self.cancel)
            cands = scanner.scan(sigs)
            rep.boot_offsets = [o for o, k in cands if k == MARKER]
            cands = [c for c in cands if c[1] != MARKER]
            rep.candidates = len(cands)
            self.events.emit("phase", name="carving")
            self._carve(cands, wanted, rep)
        except Cancelled:
            rep.stopped = "cancelled"
        except OutOfSpace as ex:
            rep.stopped = str(ex)
            self.events.emit("warning", message=str(ex))
        rep.seconds = time.monotonic() - t0
        return rep

    def _carve(self, cands, wanted, rep):
        src, n = self.src, len(self.src)
        starts = [c[0] for c in cands]
        bad = src.bad_ranges()
        prog = Progress(self.events, "carving", len(cands), unit="items")
        covered, idx = 0, 0
        for k, (start, kind) in enumerate(cands, 1):
            self.cancel.check()
            prog.update(k, saved=idx)
            if not self.opt.overlap and start < covered:
                continue
            j = bisect.bisect_right(starts, start)
            nxt = starts[j] if j < len(starts) else n
            try:
                res = self.registry.get(kind).parse(src, start, n, nxt)
            except (IndexError, ValueError, OverflowError):
                res = None
            if not res or res.end - start < self.opt.min_size or res.ext not in wanted:
                continue
            status = res.status
            if status == "ok" and overlaps(bad, start, res.end):
                status = "badsectors"
            idx += 1
            rel, digest = self.writer.save(src, start, res.end, res.ext, status, idx)
            rec = FileRecord(idx, start, res.end - start, res.ext, status, digest, rel)
            rep.files.append(rec)
            rep.stats[res.ext] = rep.stats.get(res.ext, 0) + 1
            covered = max(covered, res.end)
            self.events.emit("file", **rec.to_dict())
        prog.update(len(cands), force=True, saved=idx)
