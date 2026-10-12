// Electron main process: owns the window and the engine process; the renderer reaches both via IPC.
import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";

import { checkSudoPassword, elevated, engineCommand, startEngine, type EngineProcess, type Launch }
  from "./engineClient";

const APP_ROOT = path.resolve(__dirname, "..", "..");     // dist-electron/electron -> app/
const IS_WIN = process.platform === "win32";
let win: BrowserWindow | null = null;
let engine: EngineProcess | null = null;
let engineIsRoot = false;                                  // macOS / Linux: started through sudo

function baseLaunch(): Launch {
  return engineCommand(APP_ROOT, app.isPackaged ? process.resourcesPath : null);
}

/**
 * An AppImage runs from a FUSE mount that root cannot read, so for sudo the bundled engine is
 * copied to a temporary folder first.
 */
function rootReadable(launch: Launch): Launch {
  if (!process.env.APPIMAGE || !app.isPackaged) return launch;
  const dest = path.join(os.tmpdir(), `disk-salvage-engine-${app.getVersion()}`);
  fs.rmSync(dest, { recursive: true, force: true });
  fs.cpSync(launch.cwd, dest, { recursive: true });
  return { ...launch, cwd: dest, cmd: path.join(dest, path.basename(launch.cmd)) };
}

function launchEngine(launch: Launch): EngineProcess {
  const started = startEngine(launch, (code, stderr) => {
    if (engine !== started) return;                        // an engine we replaced on purpose
    engine = null;
    engineIsRoot = false;
    win?.webContents.send("engine:exit", { code, stderr });
  });
  engine = started;
  return started;
}

function ensureEngine(): EngineProcess {
  return engine ?? launchEngine(baseLaunch());
}

/** Windows: the .exe requires Administrator, so the whole app (and engine) is elevated by UAC. */
function isWindowsAdmin(): Promise<boolean> {
  return new Promise((resolve) => execFile("net", ["session"], { windowsHide: true }, (err) => resolve(!err)));
}

async function isElevated(): Promise<boolean> {
  if (IS_WIN) return isWindowsAdmin();
  return process.getuid?.() === 0 || engineIsRoot;
}

/** macOS / Linux: check the password with sudo, then restart the engine as root with it. */
async function elevate(password: string): Promise<{ ok: boolean; message?: string }> {
  if (IS_WIN) return { ok: await isWindowsAdmin() };
  if (!(await checkSudoPassword(password))) {
    return { ok: false, message: "That password was not accepted. Use the password of an administrator account." };
  }
  const old = engine;
  const next = launchEngine(elevated(rootReadable(baseLaunch()), password));
  old?.stop();
  try {
    await Promise.race([next.client.ready,
                        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 20000))]);
  } catch {
    launchEngine(baseLaunch());                            // fall back: image files still work
    next.stop();
    return { ok: false, message: "The recovery engine did not start with administrator rights." };
  }
  engineIsRoot = true;
  return { ok: true };
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 760,
    minHeight: 560,
    title: "Disk Salvage",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  win.removeMenu();
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) void win.loadURL(devUrl);
  else void win.loadFile(path.join(APP_ROOT, "dist", "index.html"));
  win.on("closed", () => (win = null));
}

ipcMain.on("engine:call", (e, job: number, method: string, params: Record<string, unknown>) => {
  const { client } = ensureEngine();
  const send = (channel: string, payload: unknown) => {
    if (!e.sender.isDestroyed()) e.sender.send(channel, payload);
  };
  const { result } = client.call(method, params, (msg) => send("engine:event", msg), job);
  result.then((value) => send("engine:done", { job, result: value }),
              (error) => send("engine:done", { job, error }));
});

ipcMain.handle("engine:cancel", (_e, job: number) => engine?.client.cancel(job));

ipcMain.handle("dialog:openImage", async () => {
  const r = await dialog.showOpenDialog(win!, {
    title: "Open a disk image",
    properties: ["openFile"],
    filters: [{ name: "Disk images", extensions: ["img", "dd", "raw", "bin", "iso", "dmg", "001"] },
              { name: "All files", extensions: ["*"] }],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle("dialog:saveImage", async (_e, suggested: string) => {
  const r = await dialog.showSaveDialog(win!, {
    title: "Save the drive copy as",
    defaultPath: suggested,
    filters: [{ name: "Disk image", extensions: ["img"] }],
  });
  return r.canceled ? null : r.filePath;
});

ipcMain.handle("dialog:folder", async () => {
  const r = await dialog.showOpenDialog(win!, {
    title: "Choose where to save recovered files",
    properties: ["openDirectory", "createDirectory"],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle("shell:openPath", (_e, p: string) => shell.openPath(p));
ipcMain.handle("app:isElevated", () => isElevated());
ipcMain.handle("app:needsPassword", async () => !IS_WIN && !(await isElevated()));
ipcMain.handle("app:elevate", (_e, password: string) => elevate(String(password)));

app.whenReady().then(() => {
  ensureEngine();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  engine?.stop();                           // closing stdin cancels running jobs; the engine exits
  if (process.platform !== "darwin") app.quit();
});
