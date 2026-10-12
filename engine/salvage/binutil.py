"""Small helpers for reading integers out of byte buffers and formatting sizes."""

KB, MB, GB = 1024, 1024 ** 2, 1024 ** 3


def u16(b, o, e="big"):
    return int.from_bytes(b[o:o + 2], e)


def u32(b, o, e="big"):
    return int.from_bytes(b[o:o + 4], e)


def u64(b, o, e="big"):
    return int.from_bytes(b[o:o + 8], e)


def hx(offset):
    return f"0x{offset:X}"


def human(nbytes):
    if nbytes is None:
        return "?"
    if nbytes >= GB:
        return f"{nbytes / GB:.2f} GB"
    if nbytes >= MB:
        return f"{nbytes / MB:.1f} MB"
    return f"{nbytes / KB:.0f} KB"
