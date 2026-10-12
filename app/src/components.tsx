import { useEffect, useRef, type ReactNode } from "react";

import { duration, explainError, human, percent } from "./format";
import type { JobState } from "./useJob";

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="alert err" role="alert"><b>FAULT</b>{explainError(error, window.salvage.platform)}</div>;
}

/** A framed console panel with a small uppercase label. */
export function Panel({ label, right, children, className = "" }:
    { label?: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {(label || right) && (
        <header className="panel-head">
          {label && <span className="panel-label">{label}</span>}
          {right && <span className="panel-right">{right}</span>}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Readout({ label, value, tone }: { label: string; value: ReactNode; tone?: "ok" | "warn" | "err" | "amber" }) {
  return (
    <div className="readout">
      <span className="readout-label">{label}</span>
      <span className={`readout-value ${tone ?? ""}`}>{value}</span>
    </div>
  );
}

const CELLS = 400;

/**
 * The drive as a grid of cells: read (amber), not yet read (dark), a recovered file starts here (green).
 * size: total bytes; scanned: bytes read so far; offsets: where recovered files start.
 */
export function SectorMap({ size, scanned, offsets = [], badBytes = 0 }:
    { size: number | null; scanned: number; offsets?: number[]; badBytes?: number }) {
  const hits = new Set<number>();
  if (size) for (const o of offsets) hits.add(Math.min(CELLS - 1, Math.floor((o / size) * CELLS)));
  const read = size ? Math.round((Math.min(scanned, size) / size) * CELLS) : 0;
  return (
    <div className="sectors-wrap">
      <div className="sectors" role="img"
           aria-label={size ? `${Math.round((100 * scanned) / size)}% of the drive read, ${hits.size} areas with files` : "waiting"}>
        {Array.from({ length: CELLS }, (_, i) => (
          <i key={i} className={hits.has(i) ? "hit" : i < read ? "read" : i === read && read < CELLS ? "head" : ""} />
        ))}
      </div>
      <div className="legend">
        <span><i className="read" /> read</span>
        {offsets.length > 0 && <span><i className="hit" /> files found</span>}
        <span><i /> not read yet</span>
        {badBytes > 0 && <span className="err-text">{human(badBytes)} unreadable</span>}
      </div>
    </div>
  );
}

export function Feed({ lines }: { lines: JobState["feed"] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines.length]);
  return (
    <div className="feed" ref={ref} aria-live="polite">
      {lines.length === 0 && <div className="feed-line dim">standing by…</div>}
      {lines.map((l, i) => (
        <div key={i} className={`feed-line ${l.level}`}><span className="t">{l.time}</span>{l.text}</div>
      ))}
    </div>
  );
}

export function StatsBar({ stats }: { stats: Record<string, number> }) {
  const entries = Object.entries(stats).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return null;
  return (
    <div className="stats">
      {entries.map(([ext, n]) => <span key={ext} className="stat"><b>{n}</b>{ext.toUpperCase()}</span>)}
    </div>
  );
}

/** Live telemetry for a running (or finished) job: readouts, sector map, counters and log. */
export function JobPanel({ state, onCancel, showMap = true, stopLabel = "Stop" }:
    { state: JobState; onCancel?: () => void; showMap?: boolean; stopLabel?: string }) {
  const p = state.progress;
  const active = state.running || p || state.feed.length > 1;
  return (
    <>
      {state.driveLost && (
        <div className="alert err pulse" role="status">
          <b>DRIVE LOST</b>
          The drive stopped responding at {human(state.driveLost.offset)}. Unplug it, wait a few seconds and plug it
          back in; the job continues by itself. Waiting {state.driveLost.seconds}s…
        </div>
      )}
      {active && (
        <Panel label="Telemetry"
               right={state.running
                 ? <><span className="led amber blink" />{state.phase || "starting"}
                     {onCancel && <button className="ghost small" onClick={onCancel}>{stopLabel}</button>}</>
                 : <><span className={`led ${state.error ? "red" : "green"}`} />{state.error ? "halted" : "complete"}</>}>
          <div className="readouts">
            <Readout label="Progress" value={`${percent(p).toFixed(1)}%`} tone="amber" />
            <Readout label={p?.unit === "items" ? "Checked" : "Read"}
                     value={p ? <>{p.unit === "bytes" ? human(p.done) : p.done}
                       <small> of {p.unit === "bytes" ? human(p.total) : p.total}</small></> : "—"} />
            <Readout label="Speed" value={p?.rate ? `${(p.rate / 1024 ** 2).toFixed(1)} MB/s` : "—"} />
            <Readout label="Time left" value={p?.eta != null ? duration(p.eta) : "—"} />
            {state.fileCount > 0 && <Readout label="Recovered" value={state.fileCount} tone="ok" />}
            {!!p?.bad && <Readout label="Unreadable" value={human(p.bad)} tone="err" />}
          </div>
          <div className="bar"><div style={{ width: `${percent(p)}%` }} /></div>
          {showMap && (
            <SectorMap size={state.size} scanned={state.scanned} offsets={state.offsets} badBytes={p?.bad ?? 0} />
          )}
          <StatsBar stats={state.stats} />
        </Panel>
      )}
      {state.feed.length > 0 && <Panel label="Event log"><Feed lines={state.feed} /></Panel>}
      <ErrorBox error={state.error} />
    </>
  );
}

export function Step({ code, title, intro, children, footer }:
    { code?: string; title: string; intro?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <section className="step">
      <div className="step-head">
        {code && <span className="step-code">{code}</span>}
        <h1>{title}</h1>
      </div>
      {intro && <p className="intro">{intro}</p>}
      <div className="step-body">{children}</div>
      {footer && <div className="step-footer">{footer}</div>}
    </section>
  );
}
