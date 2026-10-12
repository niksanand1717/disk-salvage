import { useCallback, useRef, useState } from "react";

import { explainError } from "./format";
import type { EngineEvent, FileEvent, Method, Progress, Results } from "./shared/protocol";

export type FeedLevel = "info" | "ok" | "warn" | "err";

export interface FeedLine {
  time: string;
  level: FeedLevel;
  text: string;
}

export interface JobState {
  running: boolean;
  phase: string;
  progress: Progress | null;
  warnings: string[];
  log: string[];
  files: FileEvent[];          // most recent first, capped
  fileCount: number;
  stats: Record<string, number>;
  offsets: number[];           // where each recovered file starts (for the sector map)
  size: number | null;         // source size, from the first byte-based progress
  scanned: number;             // bytes read so far in the scanning / imaging pass
  feed: FeedLine[];            // event log, most recent last, capped
  driveLost: { offset: number; seconds: number } | null;
  error: unknown;
}

const IDLE: JobState = { running: false, phase: "", progress: null, warnings: [], log: [], files: [],
                         fileCount: 0, stats: {}, offsets: [], size: null, scanned: 0, feed: [],
                         driveLost: null, error: null };
const MAX_FILES = 200;
const MAX_FEED = 80;

function clock(): string {
  return new Date().toLocaleTimeString([], { hour12: false });
}

function withFeed(s: JobState, level: FeedLevel, text: string): FeedLine[] {
  return [...s.feed, { time: clock(), level, text }].slice(-MAX_FEED);
}

/** Runs one engine job at a time and keeps its live state for display. */
export function useJob() {
  const [state, setState] = useState<JobState>(IDLE);
  const job = useRef<number | null>(null);

  const onEvent = useCallback((e: EngineEvent) => {
    setState((s) => {
      switch (e.event) {
        case "progress": {
          const p = e.data;
          if (p.unit !== "bytes") return { ...s, progress: p };
          return { ...s, progress: p, size: s.size ?? p.total, scanned: Math.max(s.scanned, p.done) };
        }
        case "phase":
          return { ...s, phase: e.data.name, progress: null, feed: withFeed(s, "info", `${e.data.name}`) };
        case "file": {
          const f = e.data;
          return { ...s, files: [f, ...s.files].slice(0, MAX_FILES), fileCount: s.fileCount + 1,
                   stats: { ...s.stats, [f.ext]: (s.stats[f.ext] ?? 0) + 1 }, offsets: [...s.offsets, f.offset],
                   feed: withFeed(s, f.status === "ok" ? "ok" : "warn",
                                  `recovered ${f.ext.toUpperCase()} at 0x${f.offset.toString(16)}`
                                  + (f.status !== "ok" ? ` (${f.status})` : "")) };
        }
        case "warning":
          return { ...s, warnings: [...s.warnings, e.data.message], feed: withFeed(s, "warn", e.data.message) };
        case "log":
          return { ...s, log: [...s.log, e.data.message], feed: withFeed(s, "info", e.data.message) };
        case "drive_lost":
          return { ...s, driveLost: { offset: e.data.offset, seconds: 0 },
                   feed: withFeed(s, "err", "drive stopped responding: waiting for it to come back") };
        case "drive_waiting":
          return { ...s, driveLost: s.driveLost && { ...s.driveLost, seconds: e.data.seconds } };
        case "drive_back":
          return { ...s, driveLost: null, log: [...s.log, `drive is back (${e.data.path})`],
                   feed: withFeed(s, "ok", `drive is back (${e.data.path}): continuing`) };
        default:
          return s;
      }
    });
  }, []);

  const run = useCallback(async <M extends Method>(method: M, params: Record<string, unknown>)
      : Promise<Results[M] | null> => {
    setState({ ...IDLE, running: true, feed: [{ time: clock(), level: "info", text: `${method} started` }] });
    const { job: id, result } = window.salvage.call(method, params, onEvent);
    job.current = id;
    try {
      const value = await result;
      setState((s) => ({ ...s, running: false, driveLost: null, feed: withFeed(s, "ok", `${method} finished`) }));
      return value;
    } catch (error) {
      setState((s) => ({ ...s, running: false, driveLost: null, error,
                         feed: withFeed(s, "err", explainError(error, window.salvage.platform)) }));
      return null;
    } finally {
      job.current = null;
    }
  }, [onEvent]);

  const cancel = useCallback(() => {
    if (job.current != null) void window.salvage.cancel(job.current);
  }, []);

  const reset = useCallback(() => setState(IDLE), []);

  return { state, run, cancel, reset };
}
