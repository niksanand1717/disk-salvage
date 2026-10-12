// Preload for scripts/preview-ui.cjs: a fake window.salvage with demo drives and a simulated recovery,
// so the UI can be screenshotted without real hardware. ?scene=finish makes jobs complete.
const { contextBridge } = require("electron");

const GB = 1024 ** 3;
const SIZE = 64 * GB;
const finish = new URLSearchParams(location.search).get("scene") === "finish";
const EXTS = ["jpg", "jpg", "jpg", "jpg", "heic", "mp4", "jpg", "cr2", "png", "mov"];
let job = 0;

const drives = [
  { path: "\\\\.\\PhysicalDrive0", size: 512 * GB, model: "Samsung SSD 980 PRO", serial: "S69ENF0R512", removable: false, bus: "NVMe", note: "" },
  { path: "\\\\.\\PhysicalDrive2", size: SIZE, model: "SanDisk Ultra SDXC", serial: "AA00000001", removable: true, bus: "USB", note: "" },
  { path: "\\\\.\\PhysicalDrive3", size: null, model: "Generic Card Reader", serial: "", removable: true, bus: "USB", note: "no media" },
];

const analyze = {
  source: "\\\\.\\PhysicalDrive2", size: SIZE, verdict:
    "the partition table and boot sector are fine, but the file tables (FAT / MFT / folders) are gone. Carving is the way to get the files back.",
  volumes: [{ start: 1048576, length: SIZE - 1048576, description: "MBR #1 type 0x07 NTFS/exFAT", fs: { name: "exFAT" } }],
  bad_ranges: [[123456789, 4096]],
  lines: ["drive size: 64.00 GB (68,719,476,736 bytes)", "MBR found, disk signature 0A1B2C3D", "",
          "MBR #1 type 0x07 NTFS/exFAT", "  starts at 0x100000, size 64.00 GB", '  filesystem: exFAT, 64.00 GB, cluster 131,072 bytes',
          '  label "SD CARD"', "  root folder at 0x2100000: not found (damaged)", "",
          "=> the partition table and boot sector are fine, but the file tables are gone."],
};

function simulate(method, onEvent, id) {
  return new Promise((resolve) => {
    const emit = (event, data) => onEvent({ event, job: id, data });
    if (method === "list_drives") return setTimeout(() => resolve(drives), 50);
    if (method === "analyze") return setTimeout(() => resolve(analyze), 150);
    emit("phase", { name: method === "image" ? "imaging" : "recovering" });
    const target = finish ? 1 : 0.48;
    let k = 0, idx = 0;
    const t = setInterval(() => {
      k += 1;
      const done = Math.min(target, k / 30) * SIZE;
      // like the real engine: files are saved while the scan is running, and only behind the scan position
      emit("progress", { phase: method === "image" ? "imaging" : "recovering", done, total: SIZE, unit: "bytes",
                         rate: 41.7 * 1024 ** 2, eta: (SIZE - done) / (41.7 * 1024 ** 2), candidates: idx * 2,
                         bad: method === "image" && k > 8 ? 8192 : undefined });
      if (method === "recover") {
        for (let j = 0; j < 3; j++) {
          idx += 1;
          const ext = EXTS[idx % EXTS.length];
          const off = Math.floor(Math.random() * done / 4096) * 4096;
          const status = idx % 17 === 0 ? "badsectors" : "ok";
          emit("file", { idx, offset: off, length: 2_000_000 + idx * 7919, ext, status,
                         path: `${ext}/${status === "ok" ? `IMG_${String(4000 + idx).padStart(4, "0")}` : `${String(idx).padStart(6, "0")}_0x${off.toString(16)}_badsectors`}.${ext}` });
        }
        if (k === 10) emit("warning", { message: "unreadable area at 11.5 GB: 4 KB read as zeros" });
      }
      if (k / 30 >= target) {
        clearInterval(t);
        if (finish) resolve(method === "image"
          ? { path: "E:\\Backups\\card.img", size: SIZE, copied: SIZE, done: true, bad: [[1, 8192]], bad_bytes: 8192, stopped: "", seconds: 1580 }
          : { source: "\\\\.\\PhysicalDrive2", out_dir: "E:\\Rescued", size: SIZE, candidates: 1840, saved: idx,
              stats: { jpg: 61, heic: 9, mp4: 9, cr2: 5, png: 4, mov: 2 }, stopped: "", seconds: 1834,
              bad_ranges: [[123456789, 4096]], lost_volumes: [], verdict: analyze.verdict, dry_run: false,
              post: { partial: { repaired: 3 }, names: { renamed: 0 }, dates: { renamed: 71 }, dedupe: { duplicates: 4 } } });
      }
    }, 40);
  });
}

contextBridge.exposeInMainWorld("salvage", {
  call(method, params, onEvent) {
    const id = ++job;
    return { job: id, result: simulate(method, onEvent ?? (() => {}), id) };
  },
  cancel: async () => {},
  openImageFile: async () => "E:\\Backups\\SanDisk Ultra 2026-10-13.img",
  saveImageFile: async (s) => `E:\\Backups\\${s}`,
  chooseFolder: async () => "E:\\Rescued",
  openPath: async () => {},
  isElevated: async () => true,
  needsPassword: async () => new URLSearchParams(location.search).get("scene") === "password",
  elevate: async () => ({ ok: false, message: "That password was not accepted." }),
  platform: "win32",
});
