"""Command line: python -m salvage <command> ...  (or the `salvage` script)."""
from __future__ import annotations

import argparse
import json
import signal
import sys

from salvage.binutil import MB, human
from salvage.errors import SalvageError
from salvage.events import CancelToken, ConsoleSink
from salvage.post import DEFAULT_STEPS
from salvage.service import SalvageService


def _steps(spec: str | None) -> list[str] | None:
    if spec is None:
        return None
    return [s.strip() for s in spec.split(",") if s.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="salvage", description="Recover photos and videos from damaged "
                                "drives and disk images. Sources are only ever read.")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("--timeout", type=float, default=30.0, metavar="S",
                   help="seconds to wait for a drive to answer a read (0 = forever; default 30)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("drives", help="list physical drives (needs Administrator / root)")
    sub.add_parser("formats", help="list the file types that can be recovered")

    a = sub.add_parser("analyze", help="check the partition table and filesystems")
    a.add_argument("source", help="drive (\\\\.\\PhysicalDrive1, /dev/sdb, /dev/disk2) or image file")
    a.add_argument("--raw", action="store_true", help="treat the source as a raw device")

    i = sub.add_parser("image", help="copy a drive to an image file (resumable)")
    i.add_argument("source")
    i.add_argument("dest", help="image file to create or continue")
    i.add_argument("--raw", action="store_true")

    r = sub.add_parser("recover", help="find and save photos and videos")
    r.add_argument("source")
    r.add_argument("out", help="output folder (on another drive)")
    r.add_argument("--types", help="e.g. images,videos or jpg,mp4,heic (default: all)")
    r.add_argument("--align", type=int, default=512, help="file start alignment in bytes (default 512)")
    r.add_argument("--min-size", type=int, default=2048, help="skip files smaller than this (bytes)")
    r.add_argument("--chunk-mb", type=int, help="scan chunk size; smaller = more frequent progress")
    r.add_argument("--dry-run", action="store_true", help="only list what would be saved")
    r.add_argument("--no-post", action="store_true", help="skip post-processing")
    r.add_argument("--post", help=f"post steps to run (default: {','.join(DEFAULT_STEPS)})")
    r.add_argument("--raw", action="store_true")

    q = sub.add_parser("post", help="(re)run post-processing on an output folder")
    q.add_argument("out")
    q.add_argument("--source", help="the drive / image it came from (for original names)")
    q.add_argument("--steps", help=f"comma-separated, from: {','.join(DEFAULT_STEPS)}")
    q.add_argument("--raw", action="store_true")

    sub.add_parser("serve", help="JSON-lines server on stdin/stdout (used by the desktop app)")
    return p


def _print_result(cmd: str, res, out) -> None:
    if cmd == "drives":
        if not res:
            out.write("no drives found\n")
        for d in res:
            extra = ", ".join(x for x in (d["bus"], "removable" if d["removable"] else "", d["note"]) if x)
            out.write(f"{d['path']:22s} {human(d['size']):>10}  {d['model']}"
                      + (f"  [{d['serial']}]" if d["serial"] else "") + (f"  ({extra})" if extra else "") + "\n")
    elif cmd == "formats":
        out.write(", ".join(res["formats"]) + "\n")
    elif cmd == "analyze":
        out.write("\n".join(res["lines"]) + "\n")
    elif cmd == "image":
        state = "complete" if res["done"] else f"stopped: {res['stopped']}" if res["stopped"] else "incomplete"
        out.write(f"\nimage {res['path']}: {human(res['copied'])} of {human(res['size'])} copied ({state})\n")
        if res["bad"]:
            out.write(f"  {len(res['bad'])} unreadable area(s), {human(res['bad_bytes'])} in total, "
                      "were filled with zeros\n")
        if not res["done"] and not res["stopped"].startswith("only"):
            out.write("  run the same command again to continue\n")
    elif cmd == "recover":
        out.write(f"\n{res['saved']} file(s) saved from {res['candidates']} candidate(s) "
                  f"in {res['seconds']:.0f}s\n")
        for ext, k in sorted(res["stats"].items(), key=lambda x: -x[1]):
            out.write(f"  {ext:6s} {k}\n")
        if res["stopped"]:
            out.write(f"  stopped early: {res['stopped']}\n")
        if res["bad_ranges"]:
            out.write(f"  {len(res['bad_ranges'])} unreadable area(s) read as zeros; "
                      "files touching them are marked 'badsectors'\n")
        for lv in res["lost_volumes"]:
            out.write(f"  lost volume: {lv['fs']} at {lv['offset']:#x}, {human(lv['size'])}\n")
        for step, counts in res.get("post", {}).items():
            out.write(f"  {step}: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + "\n")
        if not res["dry_run"]:
            out.write(f"  details: {res['out_dir']}/report.csv\n")
    elif cmd == "post":
        for step, counts in res.items():
            out.write(f"{step}: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        from salvage.server import serve
        for stream in (sys.stdin, sys.stdout):          # the protocol is UTF-8 whatever the console uses
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        return serve(sys.stdin, sys.stdout)

    cancel = CancelToken()

    def on_sigint(signum, frame):
        if cancel.cancelled:
            raise KeyboardInterrupt
        cancel.cancel()
        sys.stderr.write("\nstopping... (Ctrl+C again to quit at once)\n")
    signal.signal(signal.SIGINT, on_sigint)

    events = ConsoleSink(sys.stderr if args.json else sys.stdout)
    svc = SalvageService(events=events, cancel=cancel, read_timeout=args.timeout or None)
    try:
        if args.cmd == "drives":
            res = svc.list_drives()
        elif args.cmd == "formats":
            res = svc.version()
        elif args.cmd == "analyze":
            res = svc.analyze(args.source, args.raw)
        elif args.cmd == "image":
            res = svc.image(args.source, args.dest, args.raw)
        elif args.cmd == "recover":
            post = [] if args.no_post else _steps(args.post)
            res = svc.recover(args.source, args.out, args.types, args.align, args.min_size, args.dry_run,
                              post, args.chunk_mb * MB if args.chunk_mb else None, args.raw)
        else:
            res = svc.postprocess(args.out, args.source, _steps(args.steps), args.raw)
    except (SalvageError, ValueError) as ex:
        sys.stderr.write(f"error: {ex}\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return 130
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        sys.stdout.write("\n")
    else:
        _print_result(args.cmd, res, sys.stdout)
    return 1 if isinstance(res, dict) and res.get("stopped") and res["stopped"] != "cancelled" else 0
