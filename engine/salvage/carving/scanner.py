"""One sequential pass over the source, collecting sector-aligned signature hits."""
from __future__ import annotations

from salvage.binutil import MB
from salvage.events import CancelToken, EventSink, NullSink, Progress
from salvage.formats.base import Signature

HEAD = 16   # with align >= 16 only the first 16 bytes of each sector are searched


class Scanner:
    def __init__(self, src, align: int = 512, chunk_bytes: int = 256 * MB,
                 events: EventSink | None = None, cancel: CancelToken | None = None):
        if align < 1:
            raise ValueError("align must be >= 1")
        self.src, self.align = src, align
        self.chunk = max(align, (chunk_bytes // align) * align)
        self.events, self.cancel = events or NullSink(), cancel or CancelToken()

    def scan(self, signatures: list[tuple[Signature, str]]) -> list[tuple[int, str]]:
        """Sorted (offset, kind) candidates."""
        src, n, align = self.src, len(self.src), self.align
        multi = [x for x in signatures if len(x[0].pattern) > 1]
        single = [x for x in signatures if len(x[0].pattern) == 1]
        if align < HEAD and single:
            self.events.emit("warning", message="single-byte signatures (TS video, FAT boot sectors) "
                                                "need --align >= 16; skipping them")
        cands: set[tuple[int, str]] = set()
        prog = Progress(self.events, "scanning", n)
        cs = 0
        while cs < n:
            self.cancel.check()
            ce = min(n, cs + self.chunk)
            data = src[cs:ce]
            if align >= HEAD:
                self._scan_heads(data, cs, multi, single, cands)
            else:
                self._scan_linear(data, cs, ce, multi, cands)
            cs = ce
            prog.update(cs, candidates=len(cands))
        prog.update(n, force=True, candidates=len(cands))
        return sorted(cands)

    def _ok(self, sig, st):
        return sig.check is None or sig.check(self.src, st, len(self.src))

    def _scan_heads(self, data, cs, multi, single, cands):
        align = self.align
        k = (len(data) + align - 1) // align
        heads = bytearray(HEAD * k)
        for j in range(HEAD):                       # gather byte j of every sector (C speed)
            col = data[j::align]
            heads[j::HEAD] = col + b"\0" * (k - len(col))
        for sig, kind in multi:
            i = heads.find(sig.pattern)
            while i != -1:
                if i % HEAD == sig.offset:
                    st = cs + (i // HEAD) * align
                    if self._ok(sig, st):
                        cands.add((st, kind))
                i = heads.find(sig.pattern, i + 1)
        for sig, kind in single:
            col = bytes(heads[sig.offset::HEAD])
            i = col.find(sig.pattern)
            while i != -1:
                st = cs + i * align
                if self._ok(sig, st):
                    cands.add((st, kind))
                i = col.find(sig.pattern, i + 1)

    def _scan_linear(self, data, cs, ce, multi, cands):
        buf = data + self.src[ce:min(len(self.src), ce + 32)]
        for sig, kind in multi:
            i = buf.find(sig.pattern)
            while i != -1:
                st = cs + i - sig.offset
                if cs <= st < ce and st % self.align == 0 and self._ok(sig, st):
                    cands.add((st, kind))
                i = buf.find(sig.pattern, i + 1)
