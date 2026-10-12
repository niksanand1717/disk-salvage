"""The JSON-lines server and the command line."""
import io
import json
import threading
import time

from helpers import FakePlatform, Fat32Builder, make_jpeg, mbr_disk
from salvage.cli import main
from salvage.server import Server, serve
from salvage.service import SalvageService


def factory(**kw):
    return SalvageService(platform=FakePlatform(), read_timeout=None, **kw)


def run_server(*requests):
    """Send the requests and let every job finish (closing stdin would cancel them)."""
    out = io.StringIO()
    srv = Server(out, factory)
    for r in requests:
        srv.handle_line(json.dumps(r))
    srv.wait(30)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_serve_says_ready_and_cancels_on_eof():
    out = io.StringIO()
    assert serve(io.StringIO(json.dumps({"id": 1, "method": "version"}) + "\n"), out, factory) == 0
    msgs = [json.loads(x) for x in out.getvalue().splitlines()]
    assert msgs[0] == {"event": "ready", "data": {"protocol": 1}}
    assert any(m.get("id") == 1 for m in msgs)


def image(tmp_path):
    fb = Fat32Builder(8)
    fb.add_file("one.jpg", make_jpeg(5000))
    p = tmp_path / "card.img"
    p.write_bytes(mbr_disk(fb.build()))
    return str(p)


def test_version_and_errors():
    msgs = run_server({"id": 1, "method": "version"}, {"id": 2, "method": "nope"},
                      {"id": 3, "method": "analyze", "params": {"source": "missing.img"}})
    by_id = {m["id"]: m for m in msgs if "id" in m}
    assert "jpg" in by_id[1]["result"]["formats"]
    assert by_id[2]["error"]["type"] == "BadRequest"
    assert by_id[3]["error"]["type"] == "SourceUnavailable"


def test_byte_order_mark_is_ignored():
    out = io.StringIO()
    srv = Server(out, factory)
    srv.handle_line("﻿" + json.dumps({"id": 1, "method": "version"}))
    srv.wait(10)
    assert "result" in json.loads(out.getvalue())


def test_bad_json_line():
    srv_out = io.StringIO()
    Server(srv_out, factory).handle_line("{not json")
    assert json.loads(srv_out.getvalue())["error"]["type"] == "BadRequest"


def test_recover_streams_events(tmp_path):
    msgs = run_server({"id": 7, "method": "recover",
                       "params": {"source": image(tmp_path), "out_dir": str(tmp_path / "out")}})
    events = [m for m in msgs if m.get("job") == 7]
    assert {"phase", "progress", "file"} <= {m["event"] for m in events}
    result = next(m for m in msgs if m.get("id") == 7)["result"]
    assert result["saved"] == 1


def test_cancel_a_running_job():
    started, release = threading.Event(), threading.Event()

    class Slow:
        def __init__(self, events, cancel):
            self.cancel = cancel

        def version(self):
            started.set()
            while not self.cancel.cancelled:
                time.sleep(0.01)
            return {"stopped": "cancelled"}

    out = io.StringIO()
    srv = Server(out, Slow)
    srv.handle_line(json.dumps({"id": 1, "method": "version"}))
    assert started.wait(2)
    srv.handle_line(json.dumps({"id": 2, "method": "cancel", "params": {"job": 1}}))
    srv.wait(2)
    msgs = {m["id"]: m for m in map(json.loads, out.getvalue().splitlines())}
    assert msgs[2]["result"] == {"cancelled": True}
    assert msgs[1]["result"] == {"stopped": "cancelled"}


def test_cli(tmp_path, capsys):
    img, out = image(tmp_path), tmp_path / "out"
    assert main(["formats"]) == 0
    assert "jpg" in capsys.readouterr().out
    assert main(["analyze", img]) == 0
    assert "FAT32" in capsys.readouterr().out
    assert main(["recover", img, str(out)]) == 0
    text = capsys.readouterr().out
    assert "1 file(s) saved" in text and (out / "jpg" / "one.jpg").is_file()
    assert main(["--json", "post", str(out), "--steps", "dedupe"]) == 0
    assert json.loads(capsys.readouterr().out) == {"dedupe": {"duplicates": 0}}
    assert main(["recover", img, str(tmp_path / "o2"), "--types", "docx"]) == 2
    assert "unknown type" in capsys.readouterr().err
