import datetime as dt
import hashlib
import os

from helpers import exif_tiff, make_jpeg, make_mp4
from salvage.manifest import FileRecord, Manifest
from salvage.post import PostContext, run_steps
from salvage.post.metadata import MAC_EPOCH, bmff_datetime, file_datetime, jpeg_datetime, tiff_datetime
from salvage.post.partial import repair_jpeg

DATE = "2021:07:04 10:20:30"
WHEN = dt.datetime(2021, 7, 4, 10, 20, 30)


def mp4_secs(d):
    return int((d - MAC_EPOCH).total_seconds())


def test_exif_and_mvhd_dates(tmp_path):
    assert tiff_datetime(exif_tiff(DATE)) == WHEN
    assert jpeg_datetime(make_jpeg(3000, DATE)) == WHEN
    assert jpeg_datetime(make_jpeg(3000)) is None
    assert bmff_datetime(make_mp4(5000, mp4_secs(WHEN))) == WHEN
    p = tmp_path / "v.mp4"
    p.write_bytes(make_mp4(5000, mp4_secs(WHEN)))
    assert file_datetime(str(p), "mp4") == WHEN
    assert tiff_datetime(exif_tiff("0000:00:00 00:00:00")) is None


def manifest_with(tmp_path, items):
    """items: (ext, data, status) -> a Manifest whose files exist on disk like the carver writes them."""
    m = Manifest(str(tmp_path), "src.img")
    for i, (ext, data, status) in enumerate(items, 1):
        rel = f"{ext}/{i:06d}_0x{i * 0x1000:x}.{ext}"
        os.makedirs(tmp_path / ext, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
        m.files.append(FileRecord(i, i * 0x1000, len(data), ext, status, hashlib.sha256(data).hexdigest(), rel))
    m.save()
    return m


def test_date_names_and_dedupe(tmp_path):
    a = make_jpeg(3000, DATE, seed=1)
    m = manifest_with(tmp_path, [("jpg", a, "ok"), ("jpg", a, "ok"), ("jpg", make_jpeg(3000, seed=5), "ok"),
                                 ("mp4", make_mp4(5000, mp4_secs(WHEN)), "ok")])
    res = run_steps(PostContext(m), ["dates", "dedupe"])
    assert res == {"dates": {"renamed": 3}, "dedupe": {"duplicates": 1}}
    paths = [r.path for r in m.files]
    assert paths[0] == "jpg/2021-07-04_10-20-30.jpg"
    assert paths[1].startswith("duplicates/") and m.files[1].duplicate_of == paths[0]
    assert paths[2] == "jpg/000003_0x3000.jpg"            # no date: name unchanged
    assert paths[3] == "mp4/2021-07-04_10-20-30.mp4"
    for r in m.files:
        assert os.path.isfile(m.abspath(r))
    again = Manifest.load(str(tmp_path))                     # the record matches the disk
    assert [r.path for r in again.files] == paths
    assert "duplicate_of" in (tmp_path / "report.csv").read_text()


def test_repair_jpeg():
    good = make_jpeg(20000)
    damaged = good[:8000] + bytes(8192) + good[16192:]
    fixed = repair_jpeg(damaged)
    assert fixed.endswith(b"\xff\xd9") and len(fixed) <= 8002
    assert repair_jpeg(good) is None                        # nothing to fix
    assert repair_jpeg(good[:9000]).endswith(b"\xff\xd9")   # truncated file gets closed
    assert repair_jpeg(b"\xff\xd8\xff" + bytes(5000)) is None


def test_partial_photos_step(tmp_path):
    good = make_jpeg(20000)
    damaged = good[:8000] + bytes(8192) + good[16192:]
    m = manifest_with(tmp_path, [("jpg", damaged, "badsectors"), ("jpg", good, "ok")])
    assert run_steps(PostContext(m), ["partial"]) == {"partial": {"repaired": 1}}
    rep = m.files[-1]
    assert rep.status == "repaired" and rep.path.startswith("repaired/") and rep.offset == m.files[0].offset
    assert os.path.getsize(m.abspath(rep)) == rep.length


def test_unknown_step(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="unknown"):
        run_steps(PostContext(Manifest(str(tmp_path))), ["nope"])
