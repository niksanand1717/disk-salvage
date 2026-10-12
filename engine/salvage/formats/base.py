"""Format parser contract and the registry parsers add themselves to."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, NamedTuple

IMAGE, VIDEO = "image", "video"
KB, MB, GB = 1024, 1024 ** 2, 1024 ** 3
LIM_IMG, LIM_RAW, LIM_BIG = 256 * MB, 512 * MB, 64 * GB


class CarveResult(NamedTuple):
    end: int
    ext: str
    status: str = "ok"          # ok | partial | approx


def fin(end, n, ext, status="ok"):
    """Clamp to the source size; anything running past the end is 'partial'."""
    return CarveResult(n, ext, "partial") if end > n else CarveResult(end, ext, status)


QuickCheck = Callable[[object, int, int], bool]
ParseFn = Callable[[object, int, int, int], "CarveResult | None"]


@dataclass(frozen=True)
class Signature:
    pattern: bytes
    offset: int = 0                 # where the pattern sits inside the file
    check: QuickCheck | None = None


@dataclass(frozen=True)
class FormatParser:
    """kind: internal name; extensions: ext -> IMAGE/VIDEO it can produce."""
    kind: str
    extensions: dict
    signatures: tuple
    parse: ParseFn


ALIASES = {"jpeg": "jpg", "tiff": "tif", "mts": "m2ts", "vob": "mpg", "mpeg": "mpg",
           "rmvb": "rm", "asf": "wmv", "heif": "heic", "nrw": "nef", "sr2": "arw"}


class FormatRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, FormatParser] = {}

    def register(self, parser: FormatParser) -> None:
        if parser.kind in self._parsers:
            raise ValueError(f"format {parser.kind!r} registered twice")
        self._parsers[parser.kind] = parser

    def get(self, kind: str) -> FormatParser:
        return self._parsers[kind]

    def all(self) -> list[FormatParser]:
        return list(self._parsers.values())

    def extensions(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in self._parsers.values():
            out.update(p.extensions)
        return out

    def resolve_types(self, spec: str | None) -> set[str]:
        """'images,videos,heic' -> set of extensions. Empty means everything."""
        exts = self.extensions()
        if not spec:
            return set(exts)
        out: set[str] = set()
        for t in (x.strip().lower().lstrip(".") for x in spec.split(",")):
            if not t:
                continue
            if t in ("images", "image", "photos"):
                out |= {e for e, c in exts.items() if c == IMAGE}
            elif t in ("videos", "video"):
                out |= {e for e, c in exts.items() if c == VIDEO}
            else:
                t = ALIASES.get(t, t)
                if t not in exts:
                    raise ValueError(f"unknown type: {t} (supported: {', '.join(sorted(exts))})")
                out.add(t)
        return out

    def select(self, wanted: set[str]) -> list[FormatParser]:
        return [p for p in self._parsers.values() if set(p.extensions) & wanted]


DEFAULT_REGISTRY = FormatRegistry()


def register(kind: str, extensions: dict, signatures: list, registry: FormatRegistry = DEFAULT_REGISTRY):
    """Decorator: register a parse function as a format."""
    def deco(fn: ParseFn) -> ParseFn:
        registry.register(FormatParser(kind, dict(extensions), tuple(signatures), fn))
        return fn
    return deco


def native_byteorder_code(size: int) -> str:
    import array
    return next(c for c in "HILQ" if array.array(c).itemsize == size)


LITTLE = sys.byteorder == "little"
