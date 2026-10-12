import { useEffect, useState } from "react";

import { ErrorBox, Step } from "../components";
import { driveLabel, human } from "../format";
import type { DriveInfo } from "../shared/protocol";

export interface Source {
  path: string;
  label: string;
  isDrive: boolean;
  size: number | null;
}

export function SourceStep({ onPick, onBack, drivesOnly = false }:
    { onPick: (s: Source) => void; onBack: () => void; drivesOnly?: boolean }) {
  const [drives, setDrives] = useState<DriveInfo[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [elevated, setElevated] = useState(true);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setDrives(await window.salvage.call("list_drives", {}).result);
    } catch (e) {
      setError(e);
      setDrives([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    void window.salvage.isElevated().then(setElevated);
  }, []);

  async function openImage() {
    const p = await window.salvage.openImageFile();
    if (p) onPick({ path: p, label: p.split(/[\\/]/).pop() ?? p, isDrive: false, size: null });
  }

  return (
    <Step title={drivesOnly ? "Which drive do you want to copy?" : "What do you want to recover from?"}
          intro={drivesOnly
            ? "Pick the drive or memory card to copy. It is only read, never written to."
            : "Pick the damaged drive or memory card, or a disk image made earlier. Nothing is ever written to it."}
          footer={<button className="ghost" onClick={onBack}>Back</button>}>
      {!elevated && !error && (
        <div className="box info">Not running as {window.salvage.platform === "win32" ? "Administrator" : "root"}:
          drives may not be listed.{!drivesOnly && " Image files work either way."}</div>
      )}
      <ErrorBox error={error} />
      <div className="list">
        {drives?.map((d) => (
          <button key={d.path} className="card" disabled={!d.size} onClick={() => onPick(
            { path: d.path, label: driveLabel(d), isDrive: true, size: d.size })}>
            <div className="card-title">{d.model || "Unknown drive"}</div>
            <div className="muted small">
              {human(d.size)} · {d.path}{d.bus && ` · ${d.bus}`}{d.removable ? " · removable" : ""}
              {d.serial && ` · S/N ${d.serial}`}{d.note && ` · ${d.note}`}
            </div>
          </button>
        ))}
        {drives?.length === 0 && !error && <p className="muted">No drives found.</p>}
      </div>
      <div className="row">
        {!drivesOnly && <button onClick={openImage}>Open a disk image…</button>}
        <button className="ghost" onClick={refresh} disabled={loading}>{loading ? "Looking…" : "Refresh drives"}</button>
      </div>
    </Step>
  );
}
