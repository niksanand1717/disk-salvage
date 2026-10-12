# disk-salvage engine

The Python package (`salvage`) behind Disk Salvage: recovers photos and videos
from damaged drives and disk images. Standard library only; Python 3.10+.

```
python -m salvage drives                      # list physical drives (Administrator / root)
python -m salvage analyze <drive-or-image>    # partition table + filesystem report
python -m salvage image <drive> copy.img      # resumable copy; run again to continue
python -m salvage recover <source> <out-dir>  # carve, then names / dates / repair / dedupe
python -m salvage post <out-dir>              # re-run post-processing
python -m salvage serve                       # JSON-lines server used by the desktop app
```

Tests: `pip install -e ".[dev]"` then `pytest`. See the repository README for the
architecture and the protocol.
