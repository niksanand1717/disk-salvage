"""The record of what was recovered: report.json (authoritative) + report.csv (for people).

Post-processing steps rename / move files through the manifest so the record
always matches what is on disk.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass, field, fields

CSV_FIELDS = ["idx", "offset", "length", "ext", "status", "sha256", "path", "named_by", "duplicate_of"]


@dataclass
class FileRecord:
    idx: int
    offset: int
    length: int
    ext: str
    status: str             # ok | partial | approx | badsectors
    sha256: str
    path: str               # relative to the output folder, "/" separators
    named_by: str = "carver"  # carver | original | date
    duplicate_of: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Manifest:
    out_dir: str
    source: str = ""
    files: list[FileRecord] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    JSON = "report.json"
    CSV = "report.csv"

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, out_dir: str) -> "Manifest":
        with open(os.path.join(out_dir, cls.JSON), encoding="utf-8") as f:
            d = json.load(f)
        names = {x.name for x in fields(FileRecord)}
        files = [FileRecord(**{k: v for k, v in r.items() if k in names}) for r in d.get("files", [])]
        return cls(out_dir, d.get("source", ""), files, d.get("info", {}))

    def save(self) -> None:
        if not os.path.isdir(self.out_dir):
            return
        tmp = os.path.join(self.out_dir, self.JSON + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"source": self.source, "info": self.info,
                       "files": [r.to_dict() for r in self.files]}, f, indent=1)
        os.replace(tmp, os.path.join(self.out_dir, self.JSON))
        with open(os.path.join(self.out_dir, self.CSV), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            for r in self.files:
                d = r.to_dict()
                d["offset"] = hex(d["offset"])
                w.writerow([d[k] for k in CSV_FIELDS])

    # -------------------------------------------------------------- queries
    def abspath(self, rec: FileRecord) -> str:
        return os.path.join(self.out_dir, *rec.path.split("/"))

    def by_offset(self) -> dict[int, FileRecord]:
        return {r.offset: r for r in self.files}

    def existing_names(self) -> set[str]:
        return {r.path.lower() for r in self.files}

    def next_idx(self) -> int:
        return max((r.idx for r in self.files), default=0) + 1

    # ------------------------------------------------------------- changes
    def move(self, rec: FileRecord, new_rel: str) -> None:
        """Rename / move a recorded file on disk and in the record."""
        new_rel = new_rel.replace(os.sep, "/")
        dst = os.path.join(self.out_dir, *new_rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(self.abspath(rec), dst)
        rec.path = new_rel

    def unique_path(self, folder: str, stem: str, ext: str) -> str:
        taken = self.existing_names()
        rel, k = f"{folder}/{stem}.{ext}", 1
        while rel.lower() in taken or os.path.exists(os.path.join(self.out_dir, *rel.split("/"))):
            k += 1
            rel = f"{folder}/{stem}_{k}.{ext}"
        return rel
