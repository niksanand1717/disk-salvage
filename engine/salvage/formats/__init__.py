"""Format parsers. Importing this package registers every built-in format.

To add a format, write a parse function in one of these modules (or a new one
imported here) and decorate it with @register — nothing else changes.
"""
from salvage.formats import images, isobmff, raw, video  # noqa: F401  (registration side effects)
from salvage.formats.base import (DEFAULT_REGISTRY, IMAGE, VIDEO, CarveResult, FormatParser,
                                  FormatRegistry, Signature, register)


def default_registry() -> FormatRegistry:
    return DEFAULT_REGISTRY


__all__ = ["CarveResult", "FormatParser", "FormatRegistry", "Signature", "register",
           "default_registry", "IMAGE", "VIDEO"]
