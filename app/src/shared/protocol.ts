// Types for the engine's JSON-lines protocol (see engine/salvage/server.py).
// Shared by the Electron main process, the preload bridge and the renderer.

export type Method = "version" | "list_drives" | "analyze" | "image" | "recover" | "postprocess";

export interface EngineErrorDetail {
  type: string;          // e.g. AccessDenied, SameDriveError, OutOfSpace, SourceUnavailable
  message: string;
  trace?: string;
}

export interface Progress {
  phase: string;
  done: number;
  total: number;
  unit: "bytes" | "items";
  rate?: number | null;
  eta?: number | null;
  candidates?: number;
  saved?: number;
  bad?: number;
}

export interface FileEvent {
  idx: number;
  offset: number;
  length: number;
  ext: string;
  status: string;
  path: string;
}

export type EngineEvent =
  | { event: "progress"; job: number; data: Progress }
  | { event: "phase"; job: number; data: { name: string } }
  | { event: "file"; job: number; data: FileEvent }
  | { event: "log" | "warning"; job: number; data: { message: string } }
  | { event: "drive_lost"; job: number; data: { offset: number } }
  | { event: "drive_back"; job: number; data: { path: string } }
  | { event: "drive_waiting"; job: number; data: { seconds: number } };

export interface DriveInfo {
  path: string;
  size: number | null;
  model: string;
  serial: string;
  removable: boolean | null;
  bus: string;
  note: string;
}

export interface VersionInfo {
  engine: string;
  python: string;
  os: string;
  formats: string[];
  post_steps: string[];
}

export interface AnalyzeResult {
  source: string;
  size: number;
  lines: string[];
  verdict: string;
  volumes: { start: number; length: number | null; description: string; fs: { name: string } | null }[];
  bad_ranges: [number, number][];
}

export interface ImageResult {
  path: string;
  size: number;
  copied: number;
  done: boolean;
  bad: [number, number][];
  bad_bytes: number;
  stopped: string;
  seconds: number;
}

export interface LostVolume {
  offset: number;
  fs: string;
  size: number | null;
  hint: string;
}

export interface RecoverResult {
  source: string;
  out_dir: string;
  size: number;
  candidates: number;
  saved: number;
  stats: Record<string, number>;
  stopped: string;
  seconds: number;
  bad_ranges: [number, number][];
  lost_volumes: LostVolume[];
  verdict: string;
  dry_run: boolean;
  post?: Record<string, Record<string, number | string>>;
}

export interface Results {
  version: VersionInfo;
  list_drives: DriveInfo[];
  analyze: AnalyzeResult;
  image: ImageResult;
  recover: RecoverResult;
  postprocess: Record<string, Record<string, number | string>>;
}

// What the preload script exposes to the renderer as window.salvage.
export interface SalvageBridge {
  call<M extends Method>(method: M, params: Record<string, unknown>,
                         onEvent?: (e: EngineEvent) => void): { job: number; result: Promise<Results[M]> };
  cancel(job: number): Promise<void>;
  openImageFile(): Promise<string | null>;
  saveImageFile(suggested: string): Promise<string | null>;
  chooseFolder(): Promise<string | null>;
  openPath(path: string): Promise<void>;
  isElevated(): Promise<boolean>;
  /** macOS / Linux: the engine is not root yet, so ask for the administrator password. */
  needsPassword(): Promise<boolean>;
  elevate(password: string): Promise<{ ok: boolean; message?: string }>;
  platform: string;
}

export class EngineCallError extends Error {
  constructor(public detail: EngineErrorDetail) {
    super(detail.message);
    this.name = detail.type;
  }
}
