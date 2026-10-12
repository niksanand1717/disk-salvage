// Bundles the Python engine into a standalone folder (build/engine/salvage-engine/) with PyInstaller,
// so the packaged app needs no Python. Uses SALVAGE_PYTHON if set, else python / python3.
import { execFileSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const engineDir = path.resolve(appDir, "..", "engine");
const buildDir = path.join(appDir, "build");
const python = process.env.SALVAGE_PYTHON ?? (process.platform === "win32" ? "python" : "python3");

rmSync(path.join(buildDir, "engine"), { recursive: true, force: true });
execFileSync(python, [
  "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
  "--name", "salvage-engine",
  "--paths", engineDir,
  "--collect-submodules", "salvage",          // formats / platforms are imported by registration
  "--distpath", path.join(buildDir, "engine"),
  "--workpath", path.join(buildDir, "pyinstaller"),
  "--specpath", buildDir,
  path.join(engineDir, "packaging", "engine_entry.py"),
], { stdio: "inherit", cwd: appDir });

const exe = path.join(buildDir, "engine", "salvage-engine",
                      process.platform === "win32" ? "salvage-engine.exe" : "salvage-engine");
if (!existsSync(exe)) throw new Error(`engine build failed: ${exe} not found`);
execFileSync(exe, ["formats"], { stdio: "inherit" });   // smoke test: the bundle starts and lists formats
console.log(`engine bundled: ${exe}`);
