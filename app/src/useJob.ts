import { useCallback, useRef, useState } from "react";

import type { EngineEvent, FileEvent, Method, Progress, Results } from "./shared/protocol";

export interface JobState {
  running: boolean;
  phase: string;
  progress: Progress | null;
  warnings: string[];
  log: string[];
  files: FileEvent[];          // most recent first, capped
  fileCount: number;
  driveLost: { offset: number; seconds: number } | null;
  error: unknown;
}

const IDLE: JobState = { running: false, phase: "", progress: null, warnings: [], log: [], files: [],
                         fileCount: 0, driveLost: null, error: null };
const MAX_FILES = 200;

/** Runs one engine job at a time and keeps its live state for display. */
export function useJob() {
  const [state, setState] = useState<JobState>(IDLE);
  const job = useRef<number | null>(null);

  const onEvent = useCallback((e: EngineEvent) => {
    setState((s) => {
      switch (e.event) {
        case "progress":
          return { ...s, progress: e.data };
        case "phase":
          return { ...s, phase: e.data.name, progress: null };
        case "file":
          return { ...s, files: [e.data, ...s.files].slice(0, MAX_FILES), fileCount: s.fileCount + 1 };
        case "warning":
          return { ...s, warnings: [...s.warnings, e.data.message] };
        case "log":
          return { ...s, log: [...s.log, e.data.message] };
        case "drive_lost":
          return { ...s, driveLost: { offset: e.data.offset, seconds: 0 } };
        case "drive_waiting":
          return { ...s, driveLost: s.driveLost && { ...s.driveLost, seconds: e.data.seconds } };
        case "drive_back":
          return { ...s, driveLost: null, log: [...s.log, `drive is back (${e.data.path})`] };
        default:
          return s;
      }
    });
  }, []);

  const run = useCallback(async <M extends Method>(method: M, params: Record<string, unknown>)
      : Promise<Results[M] | null> => {
    setState({ ...IDLE, running: true });
    const { job: id, result } = window.salvage.call(method, params, onEvent);
    job.current = id;
    try {
      const value = await result;
      setState((s) => ({ ...s, running: false, driveLost: null }));
      return value;
    } catch (error) {
      setState((s) => ({ ...s, running: false, driveLost: null, error }));
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
