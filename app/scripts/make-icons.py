"""Stitch the tiles from render-assets.cjs and produce every icon / image the project uses.

    python scripts/make-icons.py        (needs Pillow; run render-assets.cjs with Electron first)

Outputs
  assets/logo-{1024,512,256,128}.png    README / docs
  assets/social-preview.png             1280x640, GitHub "Social preview"
  app/build-resources/icon.png          1024, electron-builder source icon
  app/build-resources/icon.ico          Windows (16-256, small sizes use the simplified logo)
  app/build-resources/icon.icns         macOS
  app/build-resources/icons/NxN.png     Linux (16-512)
  app/public/logo.svg                   favicon / in-app logo
"""
import json
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"
RENDERED = ASSETS / "rendered"
BUILD = ROOT / "app" / "build-resources"
SMALL = {16, 24, 32, 48}                       # sizes drawn from the simplified logo


def stitch(name: str) -> Image.Image:
    meta = json.loads((RENDERED / f"_{name}.json").read_text())
    img = Image.new("RGBA", (meta["width"], meta["height"]), (0, 0, 0, 0))
    for t in meta["tiles"]:
        tile = Image.open(RENDERED / t["file"]).convert("RGBA")
        img.paste(tile.crop((0, 0, t["w"], t["h"])), (t["x"], t["y"]))
    return img


def sized(src: Image.Image, n: int) -> Image.Image:
    return src.resize((n, n), Image.LANCZOS)


def main() -> None:
    full, small = stitch("logo"), stitch("logo-small")
    social = stitch("social-preview@2x").resize((1280, 640), Image.LANCZOS).convert("RGB")

    def pick(n):
        return sized(small if n in SMALL else full, n)

    for n in (1024, 512, 256, 128):
        sized(full, n).save(ASSETS / f"logo-{n}.png", optimize=True)
    social.save(ASSETS / "social-preview.png", optimize=True)

    BUILD.mkdir(parents=True, exist_ok=True)
    full.save(BUILD / "icon.png", optimize=True)
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    pick(256).save(BUILD / "icon.ico", sizes=[(n, n) for n in ico_sizes],
                   append_images=[pick(n) for n in ico_sizes[:-1]])
    full.save(BUILD / "icon.icns")
    icons = BUILD / "icons"
    icons.mkdir(exist_ok=True)
    for n in (16, 24, 32, 48, 64, 128, 256, 512):
        pick(n).save(icons / f"{n}x{n}.png", optimize=True)

    public = ROOT / "app" / "public"
    public.mkdir(exist_ok=True)
    shutil.copy(ASSETS / "logo.svg", public / "logo.svg")
    shutil.rmtree(RENDERED)
    print("icons written:", ", ".join(sorted(p.name for p in BUILD.rglob("*") if p.is_file())))


if __name__ == "__main__":
    main()
