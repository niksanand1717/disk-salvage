"""Move byte-identical copies (same sha256) into duplicates/, keeping the best-named one."""
from __future__ import annotations

from salvage.post.base import PostContext

STATUS_RANK = {"ok": 0, "badsectors": 1, "approx": 2, "partial": 3, "repaired": 4}
NAME_RANK = {"original": 0, "date": 1, "carver": 2}


def keep_rank(rec):
    return STATUS_RANK.get(rec.status, 9), NAME_RANK.get(rec.named_by, 9), rec.idx


class Dedupe:
    name, title = "dedupe", "separating duplicates"

    def run(self, ctx: PostContext) -> dict:
        m = ctx.manifest
        groups: dict[str, list] = {}
        for r in m.files:
            if r.sha256 and not r.duplicate_of:
                groups.setdefault(r.sha256, []).append(r)
        moved = 0
        for recs in groups.values():
            if len(recs) < 2:
                continue
            ctx.cancel.check()
            keep, *rest = sorted(recs, key=keep_rank)
            for r in rest:
                stem, ext = r.path.rsplit("/", 1)[-1].rsplit(".", 1)
                m.move(r, m.unique_path("duplicates", stem, ext))
                r.duplicate_of = keep.path
                moved += 1
        return {"duplicates": moved}
