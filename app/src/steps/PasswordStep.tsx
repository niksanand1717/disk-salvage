import { useState, type FormEvent } from "react";

import { Panel, Step } from "../components";

/** macOS / Linux: reading drives needs root, so the engine is restarted through sudo with this password. */
export function PasswordStep({ onDone }: { onDone: (elevated: boolean) => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await window.salvage.elevate(password);
    setPassword("");
    setBusy(false);
    if (r.ok) onDone(true);
    else setError(r.message ?? "Could not get administrator rights.");
  }

  return (
    <Step title="Authorization required"
          intro={<>Reading drives directly needs administrator rights. Enter the password of an administrator
            account on this {window.salvage.platform === "darwin" ? "Mac" : "computer"}. It is handed to the
            system (sudo) once and never stored.</>}>
      <Panel label="Access control" right={<><span className={`led ${busy ? "amber blink" : "amber"}`} />
        {busy ? "verifying" : "awaiting credentials"}</>}>
        <form className="password" onSubmit={submit}>
          <input type="password" autoFocus value={password} placeholder="Administrator password"
                 aria-label="Administrator password" onChange={(e) => setPassword(e.target.value)} disabled={busy} />
          <div className="row">
            <button type="submit" disabled={!password || busy}>{busy ? "Verifying…" : "Authorize"}</button>
            <button type="button" className="ghost" onClick={() => onDone(false)} disabled={busy}>
              Continue without (image files only)</button>
          </div>
          {error && <div className="alert err" role="alert"><b>DENIED</b>{error}</div>}
        </form>
      </Panel>
    </Step>
  );
}
