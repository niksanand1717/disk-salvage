import { useState } from "react";

import { JobPanel, Panel, Step } from "../components";
import { duration, human } from "../format";
import type { ImageResult } from "../shared/protocol";
import { useJob } from "../useJob";
import type { Source } from "./SourceStep";

/** e.g. "SanDisk Ultra 2026-10-12.img" */
export function suggestedImageName(source: Source, today = new Date()): string {
  const model = source.label.split(" — ")[0].replace(/[<>:"/\\|?*\x00-\x1f]/g, "").trim() || "drive";
  return `${model} ${today.toISOString().slice(0, 10)}.img`;
}

function folderOf(p: string): string {
  const i = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return i > 0 ? p.slice(0, i) : p;
}

export function ImageStep({ code, source, standalone, onBack, onNext, onFinish }: {
  code?: string;
  source: Source;
  standalone: boolean;                         // copy-only mode (no recovery planned)
  onBack: () => void;
  onNext: (image: ImageResult | null) => void;
  onFinish: () => void;
}) {
  const job = useJob();
  const [dest, setDest] = useState<string | null>(null);
  const [res, setRes] = useState<ImageResult | null>(null);

  async function choose() {
    const p = await window.salvage.saveImageFile(suggestedImageName(source));
    if (p) {
      setDest(p);
      setRes(null);
    }
  }

  async function start() {
    if (!dest) return;
    setRes(await job.run("image", { source: source.path, dest }));
  }

  const running = job.state.running;
  const usable = res && res.copied > 0;
  const intro = standalone
    ? <>Every sector of {source.label} is copied into one .img file. You need {human(source.size)} free on another
        drive. Areas that cannot be read are filled with zeros and listed. To continue an unfinished copy, choose
        the same file again (confirm "replace": it is continued, not overwritten).</>
    : <>A failing drive can get worse with every read. Copying it once to an image file, then recovering from the
        copy, reads each area only one time. You need {human(source.size)} free on another drive. If the copy
        stops, run it again with the same file and it continues.</>;

  return (
    <Step code={code} title={standalone ? "Capture drive to image" : "Capture first (recommended)"} intro={intro}
          footer={<>
            <button className="ghost" onClick={onBack} disabled={running}>Back</button>
            {standalone
              ? <button className="ghost" onClick={onFinish} disabled={running}>Done</button>
              : <button className="ghost" onClick={() => onNext(null)} disabled={running}>
                  Skip: recover straight from the drive</button>}
            <button onClick={() => onNext(res)} disabled={!usable || running}>
              {standalone ? "Recover photos from this copy ▸" : "Recover from the copy ▸"}</button>
          </>}>
      <Panel label="Capture setup">
        <div className="row">
          <button className="ghost" onClick={choose} disabled={running}>Choose image file…</button>
          <span className={`path ${dest ? "" : "none"}`}>{dest ?? "no file chosen"}</span>
        </div>
        <div className="row">
          <button onClick={start} disabled={!dest || running}>
            {res && !res.done ? "Continue capture" : "Start capture"}</button>
          {res && dest && (
            <button className="ghost" onClick={() => window.salvage.openPath(folderOf(dest))}>Show in folder</button>
          )}
        </div>
      </Panel>
      {res && (
        <div className={`alert ${res.done ? "ok" : "warn"}`}>
          <b>{res.done ? "CAPTURED" : res.stopped === "cancelled" ? "PAUSED" : "STOPPED"}</b>
          <span>
            {res.done ? "Copy complete" : res.stopped === "cancelled" ? "Copy paused" : `Copy stopped: ${res.stopped}`}:
            {" "}{human(res.copied)} of {human(res.size)} in {duration(res.seconds)}.
            {res.bad.length > 0 && ` ${human(res.bad_bytes)} could not be read and was filled with zeros.`}
            {!res.done && " Press \"Continue capture\" to go on, now or later."}
            {" "}Keep the small .map file next to the image: it records progress and unreadable areas.
          </span>
        </div>
      )}
      <JobPanel state={job.state} onCancel={job.cancel} />
    </Step>
  );
}
