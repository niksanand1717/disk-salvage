// Renders the SVG logos and the social-preview page to PNG with Electron's Chromium renderer.
// Windows caps a window at the screen's work area, so each page is captured in tiles that
// scripts/make-icons.py stitches back together (and turns into .ico / .icns / PNG sizes).
// Run with Electron (not Node):  electron scripts/render-assets.cjs
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { app, BrowserWindow } = require("electron");

app.commandLine.appendSwitch("force-device-scale-factor", "1");
app.disableHardwareAcceleration();

const TILE = 512;
const assets = path.resolve(__dirname, "..", "..", "assets");
const out = path.join(assets, "rendered");

const JOBS = [
  { src: "logo.svg", name: "logo", w: 1024, h: 1024, wrap: true },
  { src: "logo-small.svg", name: "logo-small", w: 1024, h: 1024, wrap: true },
  { src: "social-preview.html", name: "social-preview@2x", w: 1280, h: 640, zoom: 2 },
];

async function render(job) {
  let page = path.join(assets, job.src);
  if (job.wrap) {                       // an <img> page, so the SVG is drawn at exactly w x h
    page = path.join(out, `_${job.name}.html`);
    fs.writeFileSync(page, `<!doctype html><html><body style="margin:0;background:transparent">
      <img src="${pathToFileURL(path.join(assets, job.src))}" style="display:block;width:${job.w}px;height:${job.h}px">
      </body></html>`);
  }
  const zoom = job.zoom ?? 1;
  const W = job.w * zoom, H = job.h * zoom;            // output size in pixels
  const win = new BrowserWindow({ width: TILE, height: TILE, show: false, frame: false, transparent: true,
                                  useContentSize: true, webPreferences: { offscreen: true } });
  await win.loadFile(page);
  win.webContents.setZoomFactor(zoom);
  await new Promise((r) => setTimeout(r, 600));        // let images and fonts settle
  const tiles = [];
  for (let y = 0; y < H; y += TILE) {
    for (let x = 0; x < W; x += TILE) {
      // shift the page under the window (only the root hides overflow, so nothing is clipped)
      await win.webContents.executeJavaScript(`(() => { const s = document.documentElement.style;
        s.transform = "translate(${-x / zoom}px, ${-y / zoom}px)"; s.transformOrigin = "0 0";
        s.overflow = "hidden"; })()`);
      await new Promise((r) => setTimeout(r, 150));
      const w = Math.min(TILE, W - x), h = Math.min(TILE, H - y);
      const img = await win.webContents.capturePage({ x: 0, y: 0, width: w, height: h });
      const file = `_${job.name}_${x}_${y}.png`;
      fs.writeFileSync(path.join(out, file), img.toPNG());
      tiles.push({ file, x, y, w, h });
    }
  }
  win.destroy();
  if (job.wrap) fs.rmSync(page);
  fs.writeFileSync(path.join(out, `_${job.name}.json`), JSON.stringify({ name: job.name, width: W, height: H, tiles }));
  console.log(`${job.name}: ${W}x${H} in ${tiles.length} tiles`);
}

app.on("window-all-closed", () => {});          // closing one render window must not quit the app

app.whenReady().then(async () => {
  fs.mkdirSync(out, { recursive: true });
  try {
    for (const job of JOBS) await render(job);
  } catch (err) {
    console.error(err);
    app.exit(1);
    return;
  }
  app.quit();
});
