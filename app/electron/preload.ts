// The typed bridge the renderer sees as window.salvage. No Node access leaks through.
import { contextBridge, ipcRenderer } from "electron";

import type { EngineEvent, Method, Results, SalvageBridge } from "../src/shared/protocol";

interface Job {
  onEvent?: (e: EngineEvent) => void;
  resolve(v: unknown): void;
  reject(e: unknown): void;
}

const jobs = new Map<number, Job>();
let nextJob = 1;

ipcRenderer.on("engine:event", (_e, msg: EngineEvent) => jobs.get(msg.job)?.onEvent?.(msg));
ipcRenderer.on("engine:done", (_e, msg: { job: number; result?: unknown; error?: unknown }) => {
  const j = jobs.get(msg.job);
  if (!j) return;
  jobs.delete(msg.job);
  if (msg.error) j.reject(msg.error);
  else j.resolve(msg.result);
});
ipcRenderer.on("engine:exit", (_e, info: { code: number | null; stderr: string }) => {
  for (const j of jobs.values()) j.reject({ type: "EngineStopped", message: `the engine stopped: ${info.stderr || info.code}` });
  jobs.clear();
});

const bridge: SalvageBridge = {
  call<M extends Method>(method: M, params: Record<string, unknown>, onEvent?: (e: EngineEvent) => void) {
    const job = nextJob++;
    const result = new Promise<Results[M]>((resolve, reject) => {
      jobs.set(job, { onEvent, resolve: resolve as (v: unknown) => void, reject });
    });
    ipcRenderer.send("engine:call", job, method, params);
    return { job, result };
  },
  cancel: (job) => ipcRenderer.invoke("engine:cancel", job),
  openImageFile: () => ipcRenderer.invoke("dialog:openImage"),
  saveImageFile: (suggested) => ipcRenderer.invoke("dialog:saveImage", suggested),
  chooseFolder: () => ipcRenderer.invoke("dialog:folder"),
  openPath: (p) => ipcRenderer.invoke("shell:openPath", p),
  isElevated: () => ipcRenderer.invoke("app:isElevated"),
  needsPassword: () => ipcRenderer.invoke("app:needsPassword"),
  elevate: (password) => ipcRenderer.invoke("app:elevate", password),
  platform: process.platform,
};

contextBridge.exposeInMainWorld("salvage", bridge);
