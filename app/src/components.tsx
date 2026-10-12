import type { ReactNode } from "react";

import { explainError, human, percent, progressText } from "./format";
import type { JobState } from "./useJob";

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="box error" role="alert">{explainError(error, window.salvage.platform)}</div>;
}

export function JobPanel({ state, onCancel }: { state: JobState; onCancel?: () => void }) {
  const p = state.progress;
  return (
    <div className="job">
      {state.driveLost && (
        <div className="box warn" role="status">
          The drive stopped responding at {human(state.driveLost.offset)}. Unplug it, wait a few seconds and
          plug it back in — recovery continues by itself. Waiting {state.driveLost.seconds}s…
        </div>
      )}
      {(state.running || p) && (
        <>
          <div className="job-head">
            <span className="phase">{state.phase || "starting"}</span>
            {state.running && onCancel && <button className="ghost" onClick={onCancel}>Stop</button>}
          </div>
          <div className="bar" aria-label="progress"><div style={{ width: `${percent(p)}%` }} /></div>
          {p && <div className="muted small">{progressText(p)}
            {p.candidates != null && ` · ${p.candidates} candidates`}
            {p.saved != null && ` · ${p.saved} saved`}
            {!!p.bad && ` · ${human(p.bad)} unreadable`}</div>}
        </>
      )}
      {state.warnings.length > 0 && (
        <ul className="warnings">{state.warnings.slice(-5).map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}
      <ErrorBox error={state.error} />
    </div>
  );
}

export function Step({ title, intro, children, footer }:
    { title: string; intro?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <section className="step">
      <h1>{title}</h1>
      {intro && <p className="intro">{intro}</p>}
      <div className="step-body">{children}</div>
      {footer && <div className="step-footer">{footer}</div>}
    </section>
  );
}
