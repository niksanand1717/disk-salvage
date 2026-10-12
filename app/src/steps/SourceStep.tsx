import { useEffect, useState } from "react";

import { ErrorBox, Panel, Step } from "../components";
import { driveLabel, human } from "../format";
import type { DriveInfo } from "../shared/protocol";

export interface Source {
  path: string;
  label: string;
  isDrive: boolean;
  size: number | null;
}

export function SourceStep({ code, onPick, onBack, drivesOnly = false }:
    { code?: string; onPick: (s: Source) => void; onBack: () => void; drivesOnly?: boolean }) {
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
    <Step code={code} title={drivesOnly ? "Select target drive" : "Select source"}
          intro={drivesOnly
            ? "Pick the drive or memory card to copy. It is only read, never written to."
            : "Pick the damaged drive or memory card, or a disk image made earlier. Nothing is ever written to it."}
          footer={<button className="ghost" onClick={onBack}>Back</button>}>
      {!elevated && !error && (
        <div className="alert warn"><b>LIMITED</b>Not running as
          {window.salvage.platform === "win32" ? " Administrator" : " root"}: drives may not be listed.
          {!drivesOnly && " Image files work either way."}</div>
      )}
      <ErrorBox error={error} />
      <Panel label={`Detected drives${drives ? ` · ${drives.length}` : ""}`}
             right={<button className="ghost small" onClick={refresh} disabled={loading}>
               {loading ? "Scanning…" : "Rescan"}</button>}>
        <div className="list">
          {drives?.map((d, i) => (
            <button key={d.path} className="card" disabled={!d.size} onClick={() => onPick(
              { path: d.path, label: driveLabel(d), isDrive: true, size: d.size })}>
              <span className="card-icon">D{String(i).padStart(2, "0")}</span>
              <span>
                <div className="card-title">{d.model || "Unknown drive"}</div>
                <div className="card-meta">
                  {human(d.size)} · {d.path}{d.bus && ` · ${d.bus}`}{d.removable ? " · removable" : ""}
                  {d.serial && ` · S/N ${d.serial}`}{d.note && ` · ${d.note}`}
                </div>
              </span>
              <span className="card-go">SELECT ▸</span>
            </button>
          ))}
          {drives?.length === 0 && !error && <p className="muted small">No drives found. Plug it in and press Rescan.</p>}
          {drives === null && <p className="muted small">Scanning for drives…</p>}
        </div>
        <p className="dim small">Not sure which one? Unplug it, press Rescan, plug it back in and rescan: the one that
          appears is yours.</p>
      </Panel>
      {!drivesOnly && (
        <div className="row">
          <button className="ghost" onClick={openImage}>Open a disk image…</button>
          <span className="dim small">.img, .dd, .raw, .iso…: a copy made earlier with Disk Salvage or another tool</span>
        </div>
      )}
    </Step>
  );
}
