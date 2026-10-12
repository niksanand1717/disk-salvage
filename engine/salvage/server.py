"""JSON-lines server: the desktop app talks to the engine through this.

Request   {"id": 7, "method": "recover", "params": {...}}
Event     {"event": "progress", "job": 7, "data": {...}}
Response  {"id": 7, "result": {...}}  or  {"id": 7, "error": {"type": "...", "message": "..."}}

Every request runs in its own thread; {"method": "cancel", "params": {"job": 7}}
stops job 7. The server exits when stdin closes.
"""
from __future__ import annotations

import json
import threading
import traceback
from typing import Callable, TextIO

from salvage.errors import SalvageError
from salvage.events import CancelToken, JsonLinesSink
from salvage.service import SalvageService

ServiceFactory = Callable[..., SalvageService]
METHODS = {"version", "list_drives", "analyze", "image", "recover", "postprocess"}


class Server:
    def __init__(self, out: TextIO, service_factory: ServiceFactory = SalvageService):
        self.out = out
        self.lock = threading.Lock()
        self.factory = service_factory
        self.jobs: dict[object, CancelToken] = {}
        self.threads: list[threading.Thread] = []

    def _send(self, msg: dict) -> None:
        line = json.dumps(msg, default=str)
        with self.lock:
            self.out.write(line + "\n")
            self.out.flush()

    def _error(self, rid, ex: BaseException) -> None:
        etype = type(ex).__name__
        detail = {"type": etype, "message": str(ex) or etype}
        if not isinstance(ex, (SalvageError, ValueError, TypeError)):
            detail["trace"] = traceback.format_exc(limit=8)
        self._send({"id": rid, "error": detail})

    def handle_line(self, line: str) -> None:
        line = line.strip().lstrip("﻿")        # some shells prepend a byte-order mark
        if not line:
            return
        try:
            req = json.loads(line)
            rid, method, params = req.get("id"), req["method"], req.get("params") or {}
        except (ValueError, KeyError, AttributeError) as ex:
            self._send({"id": None, "error": {"type": "BadRequest", "message": f"bad request: {ex}"}})
            return
        if method == "cancel":
            tok = self.jobs.get(params.get("job"))
            if tok:
                tok.cancel()
            self._send({"id": rid, "result": {"cancelled": bool(tok)}})
            return
        if method not in METHODS:
            self._send({"id": rid, "error": {"type": "BadRequest", "message": f"unknown method {method!r}"}})
            return
        if rid in self.jobs:
            self._send({"id": rid, "error": {"type": "BadRequest", "message": f"id {rid!r} is already running"}})
            return
        tok = CancelToken()
        self.jobs[rid] = tok
        t = threading.Thread(target=self._run, args=(rid, method, params, tok), daemon=True)
        self.threads.append(t)
        t.start()

    def _run(self, rid, method, params, tok) -> None:
        try:
            svc = self.factory(events=JsonLinesSink(self.out, rid, self.lock), cancel=tok)
            result = getattr(svc, method)(**params)
            self._send({"id": rid, "result": result})
        except BaseException as ex:  # noqa: BLE001 - every failure goes back to the caller
            self._error(rid, ex)
        finally:
            self.jobs.pop(rid, None)

    def wait(self, timeout: float | None = None) -> None:
        for t in list(self.threads):
            t.join(timeout)


def serve(inp: TextIO, out: TextIO, service_factory: ServiceFactory = SalvageService) -> int:
    srv = Server(out, service_factory)
    srv._send({"event": "ready", "data": {"protocol": 1}})
    for line in inp:
        srv.handle_line(line)
    for tok in list(srv.jobs.values()):
        tok.cancel()
    srv.wait(5)
    return 0
