import { Step } from "../components";

export type Mode = "recover" | "image";

export function ModeStep({ onPick }: { onPick: (m: Mode) => void }) {
  return (
    <Step title="What do you want to do?">
      <div className="list">
        <button className="card" onClick={() => onPick("recover")}>
          <div className="card-title">Recover photos and videos</div>
          <div className="muted small">From a damaged drive, memory card or disk image. Includes an optional
            copy of the drive first.</div>
        </button>
        <button className="card" onClick={() => onPick("image")}>
          <div className="card-title">Copy a drive to an image file</div>
          <div className="muted small">Make a sector-by-sector copy (.img) of a drive or card, for safekeeping or to
            recover from later. Unreadable areas are skipped and listed. An unfinished copy continues where it
            stopped.</div>
        </button>
      </div>
    </Step>
  );
}
