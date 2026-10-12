import pytest

from helpers import make_jpeg, make_mp4, make_png
from salvage.formats import IMAGE, VIDEO, default_registry
from salvage.sources import MemorySource

REG = default_registry()


@pytest.mark.parametrize("kind,data,ext", [
    ("jpeg", make_jpeg(7000), "jpg"),
    ("png", make_png(5000), "png"),
    ("bmff", make_mp4(30000), "mp4"),
], ids=["jpeg", "png", "mp4"])
def test_parser_finds_exact_end(kind, data, ext):
    src = MemorySource(b"\0" * 1024 + data + b"\x11" * 4096)
    res = REG.get(kind).parse(src, 1024, len(src), len(src))
    assert res is not None
    assert (res.end, res.ext, res.status) == (1024 + len(data), ext, "ok")


def test_truncated_png_is_rejected_or_partial():
    data = make_png(5000)[:-20]
    res = REG.get("png").parse(MemorySource(data), 0, len(data), len(data))
    assert res is None or res.status == "partial"


def test_jpeg_garbage_is_rejected():
    src = MemorySource(b"\xff\xd8\xff" + b"\x00" * 100)
    assert REG.get("jpeg").parse(src, 0, len(src), len(src)) is None


def test_mpo_glued_jpegs():
    data = make_jpeg(3000, seed=1) + make_jpeg(3000, seed=2)
    res = REG.get("jpeg").parse(MemorySource(data), 0, len(data), len(data))
    assert (res.end, res.ext) == (len(data), "mpo")


def test_registry_has_about_fifty_formats():
    exts = REG.extensions()
    assert len(exts) >= 45
    assert exts["jpg"] == IMAGE and exts["mp4"] == VIDEO


def test_resolve_types():
    assert REG.resolve_types("jpeg, MTS") == {"jpg", "m2ts"}
    imgs = REG.resolve_types("images")
    assert "heic" in imgs and "mp4" not in imgs
    assert REG.resolve_types(None) == set(REG.extensions())
    with pytest.raises(ValueError, match="unknown type"):
        REG.resolve_types("docx")


def test_registry_rejects_duplicates():
    from salvage.formats import FormatRegistry, register
    r = FormatRegistry()
    register("x", {"x": IMAGE}, [], r)(lambda *a: None)
    with pytest.raises(ValueError):
        register("x", {"x": IMAGE}, [], r)(lambda *a: None)
