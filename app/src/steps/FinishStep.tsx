import { Step } from "../components";
import { duration, human } from "../format";
import type { RecoverResult } from "../shared/protocol";

const STEP_TEXT: Record<string, (c: Record<string, number | string>) => string> = {
  partial: (c) => `${c.repaired} damaged photo(s) made viewable (in "repaired")`,
  names: (c) => (c.skipped ? `original names: ${c.skipped}` : `${c.renamed} file(s) got their original names back`),
  dates: (c) => `${c.renamed} file(s) named by the date they were taken`,
  dedupe: (c) => `${c.duplicates} duplicate(s) moved to "duplicates"`,
};

export function FinishStep({ result, onRestart }: { result: RecoverResult; onRestart: () => void }) {
  const stats = Object.entries(result.stats).sort((a, b) => b[1] - a[1]);
  return (
    <Step title={result.saved ? `${result.saved} file(s) recovered` : "No photos or videos were found"}
          intro={`Finished in ${duration(result.seconds)}. Everything is in ${result.out_dir}.`}
          footer={<>
            <button className="ghost" onClick={onRestart}>Recover something else</button>
            <button onClick={() => window.salvage.openPath(result.out_dir)}>Open the folder</button>
          </>}>
      {result.stopped && (
        <div className="box warn">
          {result.stopped === "cancelled" ? "Stopped before the end: only part of the drive was searched."
                                          : `Stopped early: ${result.stopped}`}
        </div>
      )}
      {stats.length > 0 && (
        <div className="chips">{stats.map(([ext, n]) => <span key={ext} className="chip">{ext} <b>{n}</b></span>)}</div>
      )}
      {result.post && (
        <ul className="plain">
          {Object.entries(result.post).map(([k, c]) => <li key={k}>{STEP_TEXT[k]?.(c) ?? `${k}: ${JSON.stringify(c)}`}</li>)}
        </ul>
      )}
      {result.bad_ranges.length > 0 && (
        <div className="box info">
          {human(result.bad_ranges.reduce((t, [, l]) => t + l, 0))} of the drive could not be read. Files that touch
          those areas end in "_badsectors" and may show grey or broken parts.
        </div>
      )}
      {result.lost_volumes.length > 0 && (
        <div className="box info">
          Found {result.lost_volumes.length} volume(s) the partition table does not point to (deleted or lost
          partitions): {result.lost_volumes.map((v) => `${v.fs} ${human(v.size)}`).join(", ")}.
        </div>
      )}
      <p className="muted small">A full list with offsets and checksums is in report.csv inside the folder.</p>
    </Step>
  );
}
