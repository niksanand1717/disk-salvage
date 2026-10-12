"""The post-processing step contract.

A step tidies an output folder after carving. It changes files only through
the Manifest (move / add records), so report.json always matches the disk.
New steps implement PostStep and are added to STEPS; nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from salvage.events import CancelToken, EventSink, NullSink
from salvage.manifest import Manifest


@dataclass
class PostContext:
    manifest: Manifest
    src: object | None = None               # the ByteSource carved from, when still available
    events: EventSink = field(default_factory=NullSink)
    cancel: CancelToken = field(default_factory=CancelToken)


class PostStep(Protocol):
    name: str
    title: str

    def run(self, ctx: PostContext) -> dict:
        """Do the work; returns counts for the summary (e.g. {"renamed": 12})."""
