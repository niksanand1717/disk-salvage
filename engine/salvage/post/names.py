"""Give carved files real names: from surviving FAT folder listings, else from capture dates."""
from __future__ import annotations

import os
import re

from salvage.formats.base import ALIASES
from salvage.fs.fatdir import scan_fat_dirs
from salvage.fs.partitions import analyze_disk
from salvage.post.base import PostContext
from salvage.post.metadata import file_datetime

BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_stem(name: str) -> str:
    stem = BAD_CHARS.sub("_", os.path.splitext(name)[0]).strip(" .")
    return stem[:120] or "file"


def ext_matches(name: str, ext: str) -> bool:
    e = os.path.splitext(name)[1].lower().lstrip(".")
    return ALIASES.get(e, e) == ext or (ext == "mpo" and e == "jpg")


def fat_volumes(ctx: PostContext) -> list[dict]:
    """FAT data areas to search: recorded at recovery time, else worked out from the source."""
    vols = ctx.manifest.info.get("fat_volumes")
    if vols is None and ctx.src is not None:
        rep = analyze_disk(ctx.src)
        vols = [{"data_start": fs.data_start, "cluster": fs.cluster, "size": fs.size}
                for fs in rep.fat_volumes()]
    return vols or []


class OriginalNames:
    name, title = "names", "restoring original file names"

    def run(self, ctx: PostContext) -> dict:
        m = ctx.manifest
        if ctx.src is None:
            return {"renamed": 0, "skipped": "source not available"}
        by_off: dict[int, list] = {}
        for r in m.files:
            if r.named_by == "carver":
                by_off.setdefault(r.offset, []).append(r)
        renamed = 0
        for v in fat_volumes(ctx):
            end = v["data_start"] + v["size"] if v.get("size") else None
            best: dict[int, object] = {}
            for e in scan_fat_dirs(ctx.src, v["data_start"], v["cluster"], end, ctx.events, ctx.cancel):
                if e.is_dir or e.offset not in by_off:
                    continue
                if e.offset not in best or (best[e.offset].deleted and not e.deleted):
                    best[e.offset] = e
            for off, e in best.items():
                for rec in by_off.pop(off):
                    if not ext_matches(e.name, rec.ext):
                        continue                # the cluster was reused by another file
                    folder = rec.path.rsplit("/", 1)[0] if "/" in rec.path else rec.ext
                    m.move(rec, m.unique_path(folder, safe_stem(e.name), rec.ext))
                    rec.named_by = "original"
                    renamed += 1
        return {"renamed": renamed}


class DateNames:
    name, title = "dates", "naming files by capture date"

    def run(self, ctx: PostContext) -> dict:
        m = ctx.manifest
        renamed = 0
        for rec in m.files:
            ctx.cancel.check()
            if rec.named_by != "carver" or rec.duplicate_of:
                continue
            d = file_datetime(m.abspath(rec), rec.ext)
            if not d:
                continue
            folder = rec.path.rsplit("/", 1)[0] if "/" in rec.path else rec.ext
            stem = d.strftime("%Y-%m-%d_%H-%M-%S")
            if rec.status not in ("ok",):
                stem += f"_{rec.status}"
            m.move(rec, m.unique_path(folder, stem, rec.ext))
            rec.named_by = "date"
            renamed += 1
        return {"renamed": renamed}
