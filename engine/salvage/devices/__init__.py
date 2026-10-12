"""Platform-specific drive access behind one interface (Strategy pattern)."""
import sys

from salvage.devices.base import DriveInfo, Platform


def get_platform() -> Platform:
    if sys.platform.startswith("win"):
        from salvage.devices.windows import WindowsPlatform
        return WindowsPlatform()
    if sys.platform == "darwin":
        from salvage.devices.macos import MacPlatform
        return MacPlatform()
    from salvage.devices.linux import LinuxPlatform
    return LinuxPlatform()


__all__ = ["DriveInfo", "Platform", "get_platform"]
