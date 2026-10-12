import { Panel, Step } from "../components";

export type Mode = "recover" | "image";

export function ModeStep({ onPick }: { onPick: (m: Mode) => void }) {
  return (
    <Step title="Select operation"
          intro="Disk Salvage only ever reads the drive you point it at. Nothing on it is changed.">
      <div className="list">
        <button className="card big" onClick={() => onPick("recover")}>
          <span className="card-icon">OP-1</span>
          <span>
            <div className="card-title">Recover photos and videos</div>
            <div className="muted small">From a damaged drive, memory card or disk image. Includes an optional copy of
              the drive first.</div>
          </span>
          <span className="card-go">START ▸</span>
        </button>
        <button className="card big" onClick={() => onPick("image")}>
          <span className="card-icon">OP-2</span>
          <span>
            <div className="card-title">Copy a drive to an image file</div>
            <div className="muted small">A sector-by-sector copy (.img) for safekeeping or to recover from later.
              Unreadable areas are skipped and listed; an unfinished copy continues where it stopped.</div>
          </span>
          <span className="card-go">START ▸</span>
        </button>
      </div>
      <Panel label="Field notes">
        <ul className="plain small">
          <li>Stop using the damaged drive: every write can overwrite what you want back.</li>
          <li>Save recovered files to a <b>different</b> drive with enough free space.</li>
          <li>Drive slow, clicking or disconnecting? Copy it first (OP-2), then recover from the copy.</li>
        </ul>
      </Panel>
    </Step>
  );
}
