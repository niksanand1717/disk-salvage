# Contributing to Disk Salvage

Thanks for helping! Bug reports, new file formats, platform fixes and documentation are all welcome.

## Ground rules

- **Never write to the source.** Anything that reads a drive or image must go through the read-only
  `ByteSource` interface. Pull requests that open a source for writing will not be merged.
- **Keep the engine dependency-free.** It uses the Python standard library only, so it runs anywhere and
  bundles easily.
- **Add tests.** Every change to the engine should come with a test in `engine/tests/`. The helpers in
  `tests/helpers.py` build synthetic files, FAT32 disks and failing drives.

## Getting started

```
git clone https://github.com/niksanand1717/disk-salvage.git
cd disk-salvage/engine
pip install -e ".[dev]"
pytest

cd ../app
npm install
npm run typecheck && npm test
npm start
```

## Adding a file format

1. Pick the module in `engine/salvage/formats/` that fits (or create one and import it in `formats/__init__.py`).
2. Write `parse(src, start, n, next_candidate)` that returns `CarveResult(end, ext, status)` or `None`.
   - `src` behaves like `bytes` (indexing, slicing, `find`).
   - Follow the format's own structure (boxes, chunks, segments) to find the exact end.
   - Return `None` quickly when the data doesn't match. False positives cost time and disk space.
3. Decorate it:

   ```python
   @register("myformat", {"myx": IMAGE}, [Signature(b"MAGIC", offset=0)])
   def parse_myformat(src, s, n, nxt):
       ...
   ```

4. Add a test with a small synthetic sample in `engine/tests/test_formats.py`.

## Adding a post-processing step

Implement `PostStep` (`name`, `title`, `run(ctx) -> dict`) in `engine/salvage/post/` and add it to `STEPS`
in `post/__init__.py`. Change files only through the `Manifest` (`move`, add records), so `report.json`
always matches what is on disk.

## Reporting bugs

Please include:

- operating system and Disk Salvage version
- the drive type (SD card, USB stick, HDD, SSD) and how it was connected
- what you did, what you expected and what happened
- the output of `salvage analyze <source>`, if possible

**Never attach disk images or recovered files that contain personal data.**

## Pull requests

- Keep each pull request focused on one change.
- Make sure `pytest` (engine) and `npm run typecheck && npm test` (app) pass.
- By contributing you agree that your contribution is licensed under the MIT License.
