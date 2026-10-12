"""The engine's use cases. The CLI and the JSON server only call this class."""
from __future__ import annotations

import os
import platform as _pyplatform
import sys

import salvage
from salvage.binutil import MB, human
from salvage.carving import CarveOptions, Carver, DryRunWriter, FolderWriter
from salvage.devices import Platform, get_platform
from salvage.errors import SalvageError, SameDriveError
from salvage.events import CancelToken, EventSink, NullSink
from salvage.formats import FormatRegistry, default_registry
from salvage.fs import BOOT_SIGNATURES, analyze_disk, find_lost_volumes, probe_fs
from salvage.imaging import Imager
from salvage.manifest import Manifest
from salvage.post import DEFAULT_STEPS, PostContext, run_steps
from salvage.sources import DeviceSource, open_source

DEVICE_SCAN_CHUNK = 64 * MB      # well under DeviceSource's 256 MB block cache


class SalvageService:
    def __init__(self, platform: Platform | None = None, registry: FormatRegistry | None = None,
                 events: EventSink | None = None, cancel: CancelToken | None = None,
                 read_timeout: float | None = 30.0):
        self.platform = platform or get_platform()
        self.registry = registry or default_registry()
        self.events, self.cancel = events or NullSink(), cancel or CancelToken()
        self.read_timeout = read_timeout

    # ------------------------------------------------------------- helpers
    def _open(self, source: str, raw: bool = False):
        return open_source(source, self.platform, self.events, self.cancel, raw, self.read_timeout)

    def check_output_location(self, source: str, out_path: str) -> None:
        """Refuse to write onto the drive being recovered: it could overwrite the very files sought."""
        if self.platform.is_device_path(source):
            disk = self.platform.disk_of_path(out_path)
            if disk and self.platform.same_disk(disk, source):
                raise SameDriveError(f"{out_path} is on the drive being recovered ({source}). "
                                     "Choose a folder on another drive.")
            return
        if os.path.normcase(os.path.abspath(out_path)) == os.path.normcase(os.path.abspath(source)):
            raise SameDriveError("the output would overwrite the image being recovered")

    # ------------------------------------------------------------ use cases
    def version(self) -> dict:
        return {"engine": salvage.__version__, "python": sys.version.split()[0],
                "os": f"{_pyplatform.system()} {_pyplatform.release()}",
                "formats": sorted(self.registry.extensions()), "post_steps": DEFAULT_STEPS}

    def list_drives(self) -> list[dict]:
        return [d.to_dict() for d in self.platform.list_drives()]

    def analyze(self, source: str, raw: bool = False) -> dict:
        src = self._open(source, raw)
        try:
            rep = analyze_disk(src, incomplete=getattr(src, "incomplete", False))
            d = rep.to_dict()
            d["lines"] = rep.lines()
            d["source"] = source
            d["bad_ranges"] = [list(x) for x in src.bad_ranges()]
            return d
        finally:
            src.close()

    def image(self, source: str, dest: str, raw: bool = False) -> dict:
        self.check_output_location(source, dest)
        src = self._open(source, raw)
        try:
            self.events.emit("log", message=f"copying {source} ({human(len(src))}) to {dest}")
            return Imager(src, dest, self.events, self.cancel).run().to_dict()
        finally:
            src.close()

    def recover(self, source: str, out_dir: str, types: str | None = None, align: int = 512,
                min_size: int = 2048, dry_run: bool = False, post: list[str] | None = None,
                scan_chunk: int | None = None, raw: bool = False) -> dict:
        wanted = self.registry.resolve_types(types)
        if not dry_run:
            self.check_output_location(source, out_dir)
            if os.path.exists(os.path.join(out_dir, Manifest.JSON)):
                raise SalvageError(f"{out_dir} already holds a recovery (report.json); choose an empty folder")
        src = self._open(source, raw)
        try:
            incomplete = getattr(src, "incomplete", False)
            if incomplete:
                self.events.emit("warning", message="this image is only partly copied; files in "
                                                    "the missing part cannot be found")
            disk = analyze_disk(src, incomplete=incomplete)
            opt = CarveOptions(align=align, min_size=min_size)
            if scan_chunk:
                opt.scan_chunk = scan_chunk
            elif isinstance(src, DeviceSource):
                opt.scan_chunk = DEVICE_SCAN_CHUNK      # fits the block cache: each area is read once
            writer = DryRunWriter() if dry_run else FolderWriter(out_dir)
            markers = BOOT_SIGNATURES if align >= 16 else []
            man = None if dry_run else Manifest(out_dir, source, info={"status": "in progress"})

            def checkpoint(files):                      # report.json always lists what is on disk
                man.files = list(files)
                man.save()

            carver = Carver(src, self.registry, writer, self.events, self.cancel, opt, markers,
                            checkpoint=None if dry_run else checkpoint)
            try:
                rep = carver.run(wanted)
            except BaseException as ex:
                if man is not None:                     # the drive or the app failed: keep what we have
                    man.files = list(carver.report.files)
                    man.info.update(status="interrupted", stopped=f"{type(ex).__name__}: {ex}")
                    man.save()
                raise
            lost = find_lost_volumes(src, rep.boot_offsets, disk.known_boot_offsets)
            fat = [{"data_start": fs.data_start, "cluster": fs.cluster, "size": fs.size}
                   for fs in disk.fat_volumes()]
            for lv in lost:
                fs = probe_fs(src, lv.offset, len(src))
                if fs and fs.name.startswith("FAT") and fs.data_start:
                    fat.append({"data_start": fs.data_start, "cluster": fs.cluster, "size": fs.size})
            summary = {"source": source, "out_dir": out_dir, "size": len(src), "candidates": rep.candidates,
                       "saved": len(rep.files), "stats": rep.stats, "stopped": rep.stopped,
                       "seconds": round(rep.seconds, 1), "bad_ranges": [list(x) for x in src.bad_ranges()],
                       "lost_volumes": [vars(x) for x in lost], "verdict": disk.verdict,
                       "dry_run": dry_run}
            if dry_run:
                summary["files"] = [r.to_dict() for r in rep.files]
                return summary
            man.files = rep.files
            man.info = {k: v for k, v in summary.items() if k != "out_dir"}
            man.info.update(fat_volumes=fat, status="stopped" if rep.stopped else "complete")
            man.save()
            steps = list(DEFAULT_STEPS if post is None else post)
            cancel = self.cancel
            if rep.stopped == "cancelled":
                # stopped early: still tidy what was found, but skip "names" (it reads the drive again)
                steps, cancel = [s for s in steps if s != "names"], CancelToken()
            if steps:
                summary["post"] = run_steps(PostContext(man, src, self.events, cancel), steps)
            return summary
        finally:
            src.close()

    def postprocess(self, out_dir: str, source: str | None = None, steps: list[str] | None = None,
                    raw: bool = False) -> dict:
        man = Manifest.load(out_dir)
        source = source or man.source
        src = None
        if source and steps is not None and "names" not in steps:
            source = None                       # only the names step reads the source
        if source:
            try:
                src = self._open(source, raw)
            except SalvageError as ex:
                self.events.emit("warning", message=f"source not available ({ex}); "
                                                    "original names will be skipped")
        try:
            return run_steps(PostContext(man, src, self.events, self.cancel), steps)
        finally:
            if src is not None:
                src.close()
