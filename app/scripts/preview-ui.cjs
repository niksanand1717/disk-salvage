// Screenshots every screen of the built UI (dist/) with simulated data (scripts/preview-mock.cjs).
// Run with Electron after `npm run build:renderer`:  electron scripts/preview-ui.cjs [outDir]
const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow } = require("electron");

app.commandLine.appendSwitch("force-device-scale-factor", "1");
app.disableHardwareAcceleration();
app.on("window-all-closed", () => {});

const APP = path.resolve(__dirname, "..");
const OUT = path.resolve(process.argv[2] ?? path.join(APP, "..", "docs", "screenshots"));
const W = 1180, H = 780;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function open(scene) {
  const win = new BrowserWindow({ width: W, height: H, show: false, useContentSize: true,
    webPreferences: { offscreen: true, preload: path.join(__dirname, "preview-mock.cjs"), contextIsolation: true, sandbox: false } });
  await win.loadFile(path.join(APP, "dist", "index.html"), { search: scene ? `scene=${scene}` : "" });
  await sleep(400);
  return win;
}

async function click(win, text) {
  const ok = await win.webContents.executeJavaScript(`(() => {
    const b = [...document.querySelectorAll("button")].find((x) => x.textContent.includes(${JSON.stringify(text)}) && !x.disabled);
    if (b) b.click(); return !!b; })()`);
  if (!ok) throw new Error(`no enabled button "${text}"`);
  await sleep(250);
}

async function shot(win, name, wait = 300) {
  await sleep(wait);
  const img = await win.webContents.capturePage();
  fs.writeFileSync(path.join(OUT, `${name}.png`), img.toPNG());
  console.log(`${name}.png ${img.getSize().width}x${img.getSize().height}`);
}

app.whenReady().then(async () => {
  try {
    fs.mkdirSync(OUT, { recursive: true });
    let win = await open("");
    await shot(win, "01-start");
    await click(win, "Recover photos and videos");
    await shot(win, "02-source");
    await click(win, "SanDisk Ultra");
    await shot(win, "03-recon", 500);
    await click(win, "Continue");
    await shot(win, "04-capture-setup");
    await click(win, "Skip");
    await click(win, "Choose output folder");
    await click(win, "Start recovery");
    await shot(win, "05-extraction", 1600);
    win.destroy();

    win = await open("finish");
    await click(win, "Recover photos and videos");
    await click(win, "SanDisk Ultra");
    await sleep(400);
    await click(win, "Continue");
    await click(win, "Skip");
    await click(win, "Choose output folder");
    await click(win, "Start recovery");
    await shot(win, "06-debrief", 2200);
    win.destroy();

    win = await open("");
    await click(win, "Copy a drive to an image file");
    await click(win, "SanDisk Ultra");
    await click(win, "Choose image file");
    await click(win, "Start capture");
    await shot(win, "07-drive-capture", 900);
    win.destroy();

    win = await open("password");
    await shot(win, "08-authorization");
    win.destroy();
  } catch (err) {
    console.error(err);
    app.exit(1);
    return;
  }
  app.quit();
});
