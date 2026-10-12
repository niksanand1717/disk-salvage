# Disk Salvage — plan

A cross-platform tool that recovers photos and videos from damaged or failing
drives and disk images, safely (never writes to the source) and tidily
(original names, dates, duplicates, damaged-photo salvage).

## Goals

1. **Safe**: sources are opened read-only; output on the source drive is refused;
   low disk space stops cleanly; every output file is a checksummed byte range.
2. **Robust on failing hardware**: image-first workflow, resumable imaging,
   automatic wait-and-reconnect when a USB drops out, read timeouts for hung
   reads, bad sectors zero-filled and reported.
3. **Useful results**: structure-aware carving of ~50 photo/video formats,
   partition/filesystem diagnosis, lost-volume search, then post-processing:
   original names from surviving FAT folders, names from EXIF/MP4 dates,
   salvage of damaged JPEGs, duplicate separation.
4. **Cross-platform**: Windows, Linux, macOS (drive listing, raw access,
   reconnect, "which disk holds this folder").
5. **Maintainable**: SOLID design, tests that run in CI on all three OSes.

## Technology

| Part   | Choice                                   | Why |
|--------|------------------------------------------|-----|
| Engine | Python 3.10+ (stdlib only), pytest       | Proven carving code; best-in-class for binary parsing; no native deps |
| UI     | Electron + React + TypeScript, Vite      | Most widely used desktop/web UI stack |
| Bridge | JSON lines over the engine's stdin/stdout | Simple, language-neutral, testable without the UI |
| CI     | GitHub Actions (Windows/Linux/macOS)     | Standard |

## Architecture

```
app/ (Electron)                         engine/ (Python package "salvage")
 renderer: React wizard   ─ IPC ─►  main process ─ stdio JSON lines ─► salvage serve
 preload: typed bridge                 EngineClient                   Server ─► SalvageService
                                                                          │
     ┌──────────────────────┬──────────────────┬───────────────┬─────────┴─────────┐
  sources/devices        formats/ (registry)  carving/        fs/               post/
  ByteSource protocol    one parser per       Scanner         partitions,       PostStep protocol:
  File/Memory/Device     format, registered   Carver          filesystems,      OriginalNames, DateNames,
  Platform strategy      by decorator         OutputWriter    FAT dir scanner   PartialPhotos, Dedupe
  (win/linux/mac)                             Manifest        lost volumes
```

### SOLID, concretely

- **S**ingle responsibility: scanning, parsing, writing, reporting, device I/O,
  platform specifics and each post-processing step live in separate classes.
- **O**pen/closed: new formats register themselves in the `FormatRegistry`;
  new post-processing steps implement `PostStep`. The carver and services do
  not change.
- **L**iskov: `FileSource`, `MemorySource` and `DeviceSource` are
  interchangeable `ByteSource`s; Windows/Linux/macOS are interchangeable
  `Platform`s.
- **I**nterface segregation: small protocols — `ByteSource`, `EventSink`,
  `OutputWriter`, `PostStep` — instead of one big interface.
- **D**ependency inversion: `Carver`, `Imager` and the post steps receive their
  source, writer, event sink and cancel token; the CLI and the JSON server only
  compose them through `SalvageService`.

## Engine protocol (UI ⇄ engine)

Request  `{"id": 7, "method": "recover", "params": {...}}`
Event    `{"event": "progress", "job": 7, "data": {...}}`
Response `{"id": 7, "result": {...}}` or `{"id": 7, "error": {"type": ..., "message": ...}}`

Methods: `version`, `list_drives`, `analyze`, `image`, `recover`,
`postprocess`, `cancel`. Every request runs in its own worker thread; long
jobs stream events tagged with the request id; `cancel` stops one by id.

## UI flow (wizard)

1. **Source** — pick a drive (with model/serial/size) or open an image file.
2. **Check** — partition table and filesystem report with a plain verdict.
3. **Image** — recommended for drives; resumable copy with live progress.
4. **Recover** — choose output folder and types; live progress and thumbnails.
5. **Finish** — post-processing (names, dates, partial photos, duplicates),
   summary, open the output folder.

Raw drives need Administrator/root; the UI detects this and explains how to
relaunch. Image files need no special rights.

## Milestones

Status (2026-10-12): 1–6 done (engine 56 tests, app 9 tests, CI workflow written but
not yet run on GitHub). Packaging and signing not started.

1. Engine package: port and split `carve.py`; platform layer; read timeouts;
   same-drive and free-space guards; bad-area flags from image maps; manifest.
2. Post-processing steps folded in from the one-off scripts.
3. CLI (`python -m salvage ...`) and JSON-lines server.
4. Test suite: formats, partitions, carving, imaging/resume, simulated failing
   drives (bad sectors, dropouts, hangs), post steps, protocol, read-only check.
5. Electron + React app wired to the engine.
6. CI, README. Later: packaging (PyInstaller engine + electron-builder),
   code signing, filesystem-level undelete, more formats.

## Out of scope for v0.1

Filesystem undelete (NTFS/exFAT), fragmented-file reassembly, documents/audio,
installers and code signing, elevation helper (run the app elevated instead).
