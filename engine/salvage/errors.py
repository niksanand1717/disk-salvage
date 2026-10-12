"""Exceptions with a meaning the CLI and the UI can explain to a user."""


class SalvageError(Exception):
    """Base class for errors that should be shown to the user as-is."""


class AccessDenied(SalvageError):
    """Raw device access needs Administrator / root."""


class SourceUnavailable(SalvageError):
    """The drive or image cannot be opened or read at all."""


class SameDriveError(SalvageError):
    """Output folder is on the drive being recovered."""


class OutOfSpace(SalvageError):
    """Not enough free space left for the next file."""


class ImageMismatch(SalvageError):
    """An existing image / map belongs to a different drive."""


class DriveDropped(OSError):
    """The drive disconnected repeatedly while reading the same area."""


class ReadTimeout(OSError):
    """The drive did not answer a read within the timeout."""
