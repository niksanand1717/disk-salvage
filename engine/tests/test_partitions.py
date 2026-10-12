from helpers import SECTOR, Fat32Builder, make_jpeg, mbr_disk
from salvage.fs import BOOT_SIGNATURES, analyze_disk, find_lost_volumes, probe_fs
from salvage.carving import Scanner
from salvage.sources import MemorySource


def fat_disk():
    fb = Fat32Builder()
    fb.add_file("IMG_0001.JPG", make_jpeg(4000))
    return fb, mbr_disk(fb.build())


def test_probe_fat32():
    fb, _ = fat_disk()
    fs = probe_fs(MemorySource(fb.build()), 0, len(fb.vol))
    assert fs.name == "FAT32"
    assert fs.label == "TESTVOL"
    assert fs.cluster == 512
    assert fs.meta_ok
    assert fs.data_start == fb.data_sec * SECTOR
    assert 6 * SECTOR in fs.backups


def test_mbr_with_fat32():
    _, disk = fat_disk()
    rep = analyze_disk(MemorySource(disk))
    assert len(rep.volumes) == 1
    v = rep.volumes[0]
    assert v.start == 2048 * SECTOR and v.fs.name == "FAT32"
    assert "MBR found" in " ".join(rep.notes)
    assert "metadata" in rep.verdict
    assert rep.fat_volumes()[0].data_start > v.start
    assert any("FAT32" in line for line in rep.lines())


def test_wiped_mbr_and_lost_volume():
    _, disk = fat_disk()
    disk[0:SECTOR] = bytes(SECTOR)
    src = MemorySource(disk)
    rep = analyze_disk(src)
    assert not rep.volumes
    assert "all zeros" in " ".join(rep.notes)
    hits = Scanner(src, 512).scan([(s, "boot") for s in BOOT_SIGNATURES])
    lost = find_lost_volumes(src, [o for o, _ in hits], rep.known_boot_offsets)
    assert lost and lost[0].offset == 2048 * SECTOR and lost[0].fs == "FAT32"
    assert all(x.offset != 2048 * SECTOR + 6 * SECTOR for x in lost)   # the backup is not reported twice


def test_partition_past_end_warns():
    _, disk = fat_disk()
    rep = analyze_disk(MemorySource(disk[:len(disk) // 2]))
    assert any("past the end" in w for w in rep.volumes[0].warnings)


def test_superfloppy():
    fb, _ = fat_disk()
    rep = analyze_disk(MemorySource(fb.build()))
    assert rep.volumes[0].description == "whole drive"
