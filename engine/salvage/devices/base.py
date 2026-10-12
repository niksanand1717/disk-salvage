from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class DriveInfo:
    path: str
    size: int | None
    model: str = ""
    serial: str = ""
    removable: bool | None = None
    bus: str = ""
    note: str = ""          # e.g. "no media"

    def to_dict(self) -> dict:
        return asdict(self)


class Platform(ABC):
    """Everything that differs between operating systems."""

    @abstractmethod
    def list_drives(self) -> list[DriveInfo]:
        """Whole physical disks. Raises AccessDenied if elevation is needed."""

    @abstractmethod
    def is_device_path(self, path: str) -> bool: ...

    @abstractmethod
    def device_size(self, f) -> int | None:
        """Size in bytes of the device behind an open handle, or None."""

    def open_device(self, path: str):
        return open(path, "rb", buffering=0)        # read-only: nothing is ever written

    def identity(self, f, path: str) -> tuple | None:
        """Something stable that tells two disks apart (model, serial...)."""
        return None

    def is_disconnect(self, f, path: str, ex: OSError, expected_size: int) -> bool:
        """Did a failed read mean 'the drive vanished' rather than 'bad sector'?"""
        return not os.path.exists(path)

    def candidate_paths(self, path: str) -> list[str]:
        """Where a replugged drive may reappear (it can be renumbered)."""
        return [path]

    def disk_of_path(self, path: str) -> str | None:
        """Device path of the physical disk that holds `path`, if known."""
        return None

    def same_disk(self, a: str, b: str) -> bool:
        return os.path.normcase(a) == os.path.normcase(b)
