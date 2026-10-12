import { useState, type FormEvent } from "react";

import { Step } from "../components";

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
    <Step title="Administrator password"
          intro={<>Reading drives directly needs administrator rights. Enter the password of an administrator
            account on this {window.salvage.platform === "darwin" ? "Mac" : "computer"}. It is passed to the
            system (sudo) once and not stored.</>}>
      <form className="password" onSubmit={submit}>
        <input type="password" autoFocus value={password} placeholder="Password" aria-label="Administrator password"
               onChange={(e) => setPassword(e.target.value)} disabled={busy} />
        <div className="row">
          <button type="submit" disabled={!password || busy}>{busy ? "Checking…" : "Continue"}</button>
          <button type="button" className="ghost" onClick={() => onDone(false)} disabled={busy}>
            Continue without (disk image files only)</button>
        </div>
        {error && <div className="box error" role="alert">{error}</div>}
      </form>
    </Step>
  );
}
