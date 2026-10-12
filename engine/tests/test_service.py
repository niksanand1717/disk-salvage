"""End to end through SalvageService: analyze, image, recover (+ post), guards, read-only."""
import hashlib
import os

import pytest

from helpers import SECTOR, FakeDrive, FakePlatform, Fat32Builder, make_jpeg, make_mp4, mbr_disk
from salvage.errors import SalvageError, SameDriveError
from salvage.events import CollectingSink
from salvage.manifest import Manifest
from salvage.service import SalvageService

PHOTO = make_jpeg(6000, "2020:01:02 03:04:05", seed=11)
VIDEO = make_mp4(30000, seed=12)
NODATE = make_jpeg(4000, seed=13)


def fat_image(tmp_path, wipe_mbr=False):
    fb = Fat32Builder()
    fb.add_file("Holiday beach.JPG", PHOTO)
    fb.add_file("clip.mp4", VIDEO, deleted=True)
    fb.add_file("scan.jpg", NODATE)
    disk = mbr_disk(fb.build())
    if wipe_mbr:
        disk[0:SECTOR] = bytes(SECTOR)
    p = tmp_path / "card.img"
    p.write_bytes(disk)
    return str(p)


def svc(platform=None):
    return SalvageService(platform=platform or FakePlatform(), events=CollectingSink(), read_timeout=None)


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_analyze_image(tmp_path):
    res = svc().analyze(fat_image(tmp_path))
    assert res["volumes"][0]["fs"]["name"] == "FAT32"
    assert any("FAT32" in x for x in res["lines"])


@pytest.mark.parametrize("wipe_mbr", [False, True])
def test_recover_restores_names_and_dates(tmp_path, wipe_mbr):
    img = fat_image(tmp_path, wipe_mbr)
    before = digest(img)
    out = tmp_path / "out"
    res = svc().recover(img, str(out))
    assert res["saved"] == 3 and res["stats"] == {"jpg": 2, "mp4": 1}
    assert bool(res["lost_volumes"]) == wipe_mbr
    m = Manifest.load(str(out))
    names = sorted(r.path for r in m.files)
    assert names == ["jpg/Holiday beach.jpg", "jpg/scan.jpg", "mp4/clip.mp4"]
    assert {r.named_by for r in m.files} == {"original"}
    for r in m.files:
        assert digest(m.abspath(r)) == r.sha256
    assert digest(img) == before                             # the source was never written


def test_recover_without_names_uses_dates(tmp_path):
    out = tmp_path / "out"
    res = svc().recover(fat_image(tmp_path), str(out), post=["dates"])
    assert res["post"] == {"dates": {"renamed": 1}}
    assert "jpg/2020-01-02_03-04-05.jpg" in [r.path for r in Manifest.load(str(out)).files]


def test_postprocess_later(tmp_path):
    img, out = fat_image(tmp_path), tmp_path / "out"
    svc().recover(img, str(out), post=[])
    assert {r.named_by for r in Manifest.load(str(out)).files} == {"carver"}
    res = svc().postprocess(str(out))
    assert res["names"]["renamed"] == 3


def test_refuses_non_empty_output_and_dry_run_writes_nothing(tmp_path):
    img, out = fat_image(tmp_path), tmp_path / "out"
    res = svc().recover(img, str(out), dry_run=True)
    assert res["saved"] == 3 and len(res["files"]) == 3 and not out.exists()
    svc().recover(img, str(out), post=[])
    with pytest.raises(SalvageError, match="already holds"):
        svc().recover(img, str(out))


def test_same_drive_guard(tmp_path):
    data = bytes(mbr_disk(Fat32Builder(8).build()))
    plat = FakePlatform({"fake://0": FakeDrive(data)}, disk_of={"X:": "fake://0", "Y:": "fake://1"})
    with pytest.raises(SameDriveError):
        svc(plat).recover("fake://0", "X:/rescued")
    with pytest.raises(SameDriveError):
        svc(plat).image("fake://0", "X:/disk.img")
    img = fat_image(tmp_path)
    with pytest.raises(SameDriveError):
        svc().image(img, img)


def test_image_then_recover_from_drive(tmp_path):
    fb = Fat32Builder(8)
    fb.add_file("a.jpg", PHOTO)
    drive = FakeDrive(bytes(mbr_disk(fb.build())), bad={2048 + 5})
    plat = FakePlatform({"fake://0": drive})
    dest = str(tmp_path / "copy.img")
    res = svc(plat).image("fake://0", dest)
    assert res["done"] and res["bad"] == [[(2048 + 5) * SECTOR, SECTOR]]
    out = tmp_path / "out"
    res = svc(plat).recover(dest, str(out))
    assert res["saved"] == 1 and res["bad_ranges"]


def test_version_and_drives():
    plat = FakePlatform({"fake://0": FakeDrive(bytes(4096))})
    s = svc(plat)
    assert "jpg" in s.version()["formats"]
    assert s.list_drives()[0]["path"] == "fake://0"
