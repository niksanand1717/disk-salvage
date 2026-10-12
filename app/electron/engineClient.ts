// Talks to `python -m salvage serve` over stdin/stdout, one JSON object per line.
import { spawn, type ChildProcess } from "node:child_process";
import * as path from "node:path";
import { createInterface } from "node:readline";

import type { EngineErrorDetail } from "../src/shared/protocol";

export interface EngineMessage {
  id?: number | null;
  event?: string;
  job?: number;
  data?: unknown;
  result?: unknown;
  error?: EngineErrorDetail;
}

interface Pending {
  resolve(value: unknown): void;
  reject(error: EngineErrorDetail): void;
  onEvent?: (msg: EngineMessage) => void;
}

/** The protocol, independent of how the engine runs (testable without a process). */
export class EngineClient {
  private pending = new Map<number, Pending>();
  private nextId = 1;
  private nextCancel = 1;
  private readyResolve!: () => void;
  readonly ready = new Promise<void>((r) => (this.readyResolve = r));

  constructor(private write: (line: string) => void) {}

  call(method: string, params: Record<string, unknown>, onEvent?: (msg: EngineMessage) => void,
       id: number = this.nextId++): { id: number; result: Promise<unknown> } {
    const result = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject, onEvent });
    });
    this.write(JSON.stringify({ id, method, params }) + "\n");
    return { id, result };
  }

  cancel(job: number): void {
    // negative ids never collide with job ids; the engine's answer is ignored
    this.write(JSON.stringify({ id: -this.nextCancel++, method: "cancel", params: { job } }) + "\n");
  }

  /** Feed one line of engine output. */
  handleLine(line: string): void {
    if (!line.trim()) return;
    let msg: EngineMessage;
    try {
      msg = JSON.parse(line);
    } catch {
      return;                                   // stray output (e.g. a warning printed by Python)
    }
    if (msg.event === "ready") {
      this.readyResolve();
      return;
    }
    if (msg.event !== undefined) {
      if (msg.job != null) this.pending.get(msg.job)?.onEvent?.(msg);
      return;
    }
    if (msg.id == null) return;
    const p = this.pending.get(msg.id);
    if (!p) return;                             // e.g. the answer to a cancel request
    this.pending.delete(msg.id);
    if (msg.error) p.reject(msg.error);
    else p.resolve(msg.result);
  }

  /** The engine went away: fail everything still waiting. */
  failAll(message: string): void {
    for (const p of this.pending.values()) p.reject({ type: "EngineStopped", message });
    this.pending.clear();
  }
}

export interface EngineProcess {
  client: EngineClient;
  proc: ChildProcess;
  stop(): void;
}

export interface Launch {
  cmd: string;
  args: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  extraEnv: Record<string, string>;     // the part of env the engine needs (passed through sudo)
  stdinPrelude?: string;                // written before any request (the sudo password)
}

const exeName = (base: string) => (process.platform === "win32" ? `${base}.exe` : base);

/**
 * How to run the engine. Packaged: the bundled executable in resources/engine.
 * Development: python -m salvage from ../engine (SALVAGE_PYTHON / SALVAGE_ENGINE_DIR override).
 */
export function engineCommand(appRoot: string, resourcesPath: string | null): Launch {
  if (resourcesPath) {
    const dir = path.join(resourcesPath, "engine");
    return { cmd: path.join(dir, exeName("salvage-engine")), args: ["serve"], cwd: dir,
             env: { ...process.env }, extraEnv: {} };
  }
  const cwd = process.env.SALVAGE_ENGINE_DIR ?? path.resolve(appRoot, "..", "engine");
  const cmd = process.env.SALVAGE_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const sep = process.platform === "win32" ? ";" : ":";
  const extraEnv = { PYTHONPATH: [cwd, process.env.PYTHONPATH].filter(Boolean).join(sep),
                     PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" };
  return { cmd, args: ["-m", "salvage", "serve"], cwd, env: { ...process.env, ...extraEnv }, extraEnv };
}

/** The same launch, run as root through sudo (macOS / Linux). The password goes to sudo on stdin. */
export function elevated(launch: Launch, password: string): Launch {
  const envArgs = Object.entries(launch.extraEnv).map(([k, v]) => `${k}=${v}`);
  return { ...launch, cmd: "sudo",
           args: ["-S", "-k", "-p", "", "env", ...envArgs, launch.cmd, ...launch.args],
           stdinPrelude: password + "\n" };
}

/** Is this the administrator password? Asks sudo once; never stores it. */
export function checkSudoPassword(password: string, timeoutMs = 15000): Promise<boolean> {
  return new Promise((resolve) => {
    const p = spawn("sudo", ["-S", "-k", "-p", "", "true"], { stdio: ["pipe", "ignore", "ignore"] });
    const timer = setTimeout(() => p.kill(), timeoutMs);
    p.on("error", () => { clearTimeout(timer); resolve(false); });
    p.on("exit", (code) => { clearTimeout(timer); resolve(code === 0); });
    p.stdin.end(password + "\n");            // EOF after one attempt: a wrong password fails at once
  });
}

export function startEngine(launch: Launch, onExit: (code: number | null, stderr: string) => void): EngineProcess {
  const { cmd, args, cwd, env } = launch;
  const proc = spawn(cmd, args, { cwd, env, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  if (launch.stdinPrelude) proc.stdin?.write(launch.stdinPrelude);
  const client = new EngineClient((line) => proc.stdin?.write(line));
  createInterface({ input: proc.stdout! }).on("line", (l) => client.handleLine(l));
  let stderr = "";
  proc.stderr?.on("data", (d: Buffer) => {
    stderr = (stderr + d.toString()).slice(-8000);
  });
  proc.on("error", (err) => {
    client.failAll(`could not start the engine (${cmd}): ${err.message}`);
    onExit(null, String(err));
  });
  proc.on("exit", (code) => {
    client.failAll(`the engine stopped (exit code ${code})`);
    onExit(code, stderr);
  });
  return { client, proc, stop: () => proc.stdin?.end() };
}
