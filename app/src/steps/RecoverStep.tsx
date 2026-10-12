import { useState } from "react";

import { JobPanel, Step } from "../components";
import { human } from "../format";
import type { RecoverResult } from "../shared/protocol";
import { useJob } from "../useJob";

const KINDS = [
  { key: "images", label: "Photos", hint: "JPEG, HEIC, RAW, PNG…" },
  { key: "videos", label: "Videos", hint: "MP4, MOV, AVI, MTS…" },
];

export function RecoverStep({ from, label, onBack, onDone }:
    { from: string; label: string; onBack: () => void; onDone: (r: RecoverResult) => void }) {
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
    <Step title="Recover photos and videos"
          intro={`From ${label}. Choose a folder on a different drive with enough free space.`}
          footer={<button className="ghost" onClick={onBack} disabled={s.running}>Back</button>}>
      <div className="row">
        <button className="ghost" onClick={async () => setOut(await window.salvage.chooseFolder())}
                disabled={s.running}>Choose output folder…</button>
        <span className="path">{out ?? "no folder chosen"}</span>
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
      </div>
      <JobPanel state={s} onCancel={job.cancel} />
      {s.fileCount > 0 && (
        <div className="found">
          <div className="muted small">{s.fileCount} file(s) saved so far</div>
          <ul>
            {s.files.slice(0, 12).map((f) => (
              <li key={f.idx}><span className={`tag ${f.status}`}>{f.ext}</span> {f.path}
                <span className="muted small"> {human(f.length)}{f.status !== "ok" && ` · ${f.status}`}</span></li>
            ))}
          </ul>
        </div>
      )}
    </Step>
  );
}
