import { useState } from "react";

import { JobPanel, Panel, Step } from "../components";
import { human } from "../format";
import type { RecoverResult } from "../shared/protocol";
import { useJob } from "../useJob";

const KINDS = [
  { key: "images", label: "Photos", hint: "JPEG, HEIC, RAW, PNG…" },
  { key: "videos", label: "Videos", hint: "MP4, MOV, AVI, MTS…" },
];

export function RecoverStep({ code, from, label, onBack, onDone }:
    { code?: string; from: string; label: string; onBack: () => void; onDone: (r: RecoverResult) => void }) {
  const job = useJob();
  const [out, setOut] = useState<string | null>(null);
  const [kinds, setKinds] = useState<Set<string>>(new Set(KINDS.map((k) => k.key)));

  function toggle(k: string) {
    const next = new Set(kinds);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setKinds(next);
  }

  async function start() {
    if (!out) return;
    const r = await job.run("recover", { source: from, out_dir: out, types: [...kinds].join(",") });
    if (r) onDone(r);
  }

  const s = job.state;
  return (
    <Step code={code} title="Extraction"
          intro={`From ${label}. Choose a folder on a different drive with enough free space.`}
          footer={<button className="ghost" onClick={onBack} disabled={s.running}>Back</button>}>
      <Panel label="Mission parameters">
        <div className="row">
          <button className="ghost" onClick={async () => setOut(await window.salvage.chooseFolder())}
                  disabled={s.running}>Choose output folder…</button>
          <span className={`path ${out ? "" : "none"}`}>{out ?? "no folder chosen"}</span>
        </div>
        <div className="row">
          {KINDS.map((k) => (
            <label key={k.key} className="check">
              <input type="checkbox" checked={kinds.has(k.key)} onChange={() => toggle(k.key)} disabled={s.running} />
              {k.label} <span className="muted small">{k.hint}</span>
            </label>
          ))}
        </div>
        <div className="row">
          <button onClick={start} disabled={!out || kinds.size === 0 || s.running}>Start recovery</button>
          {!s.running && <span className="dim small">Files are saved the moment they are found.</span>}
        </div>
      </Panel>
      {s.running && out && (
        <div className="alert ok">
          <b>LIVE</b>
          <span>Files are saved to {out} as soon as they are found: you can open the folder and look at them
            now. If you stop, or the drive gives out, everything found so far is kept.</span>
          <button className="ghost small" onClick={() => window.salvage.openPath(out)}>Open folder</button>
        </div>
      )}
      <JobPanel state={s} onCancel={job.cancel} stopLabel="Stop (keep what's found)" />
      {s.fileCount > 0 && (
        <Panel label={`Latest recoveries · ${s.fileCount} total`} className="found">
          <ul>
            {s.files.slice(0, 12).map((f) => (
              <li key={f.idx}><span className={`tag ${f.status}`}>{f.ext}</span>{f.path}
                <span className="dim"> {human(f.length)}{f.status !== "ok" && ` · ${f.status}`}</span></li>
            ))}
          </ul>
        </Panel>
      )}
    </Step>
  );
}
