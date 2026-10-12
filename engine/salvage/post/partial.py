"""Make damaged JPEGs viewable: cut at the first unreadable (zero-filled) area and close the image.

Most viewers then show the top of the photo instead of refusing the file.
The carved original is kept; the viewable copy goes to repaired/.
"""
from __future__ import annotations

import hashlib
import os

from salvage.manifest import FileRecord
from salvage.post.base import PostContext

ZERO_RUN = 4096          # this many zero bytes inside scan data means "area was not readable"
DAMAGED = {"partial", "badsectors"}


def repair_jpeg(data: bytes) -> bytes | None:
    """A shortened, properly terminated JPEG, or None if there is nothing to fix or save."""
    sos = data.find(b"\xff\xda")
    if data[:3] != b"\xff\xd8\xff" or sos == -1:
        return None
    cut = data.find(bytes(ZERO_RUN), sos)
    if cut == -1:
        if data.endswith(b"\xff\xd9"):
            return None                     # complete already
        cut = len(data)
    body = data[:cut].rstrip(b"\0")
    if len(body) <= sos + 64:               # nothing of the picture itself survived
        return None
    if body.endswith(b"\xff"):
        body = body[:-1]
    return body + b"\xff\xd9"


class PartialPhotos:
    name, title = "partial", "making damaged photos viewable"

    def run(self, ctx: PostContext) -> dict:
        m = ctx.manifest
        made = 0
        for rec in list(m.files):
            ctx.cancel.check()
            if rec.ext != "jpg" or rec.status not in DAMAGED or rec.duplicate_of:
                continue
            try:
                with open(m.abspath(rec), "rb") as f:
                    fixed = repair_jpeg(f.read())
            except OSError:
                continue
            if not fixed:
                continue
            stem = os.path.splitext(rec.path.rsplit("/", 1)[-1])[0]
            rel = m.unique_path("repaired", f"{stem}_repaired", "jpg")
            dst = os.path.join(m.out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(fixed)
            m.files.append(FileRecord(m.next_idx(), rec.offset, len(fixed), "jpg", "repaired",
                                      hashlib.sha256(fixed).hexdigest(), rel, rec.named_by))
            made += 1
        return {"repaired": made}
