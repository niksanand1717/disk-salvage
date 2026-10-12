import { Panel, Readout, StatsBar, Step } from "../components";
import { duration, human } from "../format";
import type { RecoverResult } from "../shared/protocol";

const STEP_TEXT: Record<string, (c: Record<string, number | string>) => string> = {
  partial: (c) => `${c.repaired} damaged photo(s) made viewable (in "repaired")`,
  names: (c) => (c.skipped ? `original names: ${c.skipped}` : `${c.renamed} file(s) got their original names back`),
  dates: (c) => `${c.renamed} file(s) named by the date they were taken`,
  dedupe: (c) => `${c.duplicates} duplicate(s) moved to "duplicates"`,
};

export function FinishStep({ code, result, onRestart }:
    { code?: string; result: RecoverResult; onRestart: () => void }) {
  const badBytes = result.bad_ranges.reduce((t, [, l]) => t + l, 0);
  return (
    <Step code={code} title="Debrief"
          intro={result.saved ? `Everything is in ${result.out_dir}.` : "No photos or videos were found on this source."}
          footer={<>
            <button className="ghost" onClick={onRestart}>New operation</button>
            <button onClick={() => window.salvage.openPath(result.out_dir)}>Open the folder ▸</button>
          </>}>
      {result.stopped && (
        <div className="alert warn"><b>INCOMPLETE</b>
          {result.stopped === "cancelled"
            ? `Stopped before the end: only part of the drive was searched. The ${result.saved} file(s) found up to
               that point are saved and tidied. Run the recovery again into a new folder to search the whole drive.`
            : `Stopped early: ${result.stopped}. Everything found up to that point is saved.`}
        </div>
      )}
      <Panel label="Outcome" right={<><span className={`led ${result.saved ? "green" : "amber"}`} />
        {result.saved ? "files secured" : "nothing found"}</>}>
        <div className="readouts">
          <Readout label="Recovered" value={result.saved} tone={result.saved ? "ok" : "err"} />
          <Readout label="Candidates" value={result.candidates} />
          <Readout label="Source size" value={human(result.size)} />
          <Readout label="Duration" value={duration(result.seconds) || "0s"} />
          <Readout label="Unreadable" value={badBytes ? human(badBytes) : "none"} tone={badBytes ? "err" : "ok"} />
        </div>
        <StatsBar stats={result.stats} />
      </Panel>
      {result.post && (
        <Panel label="Post-processing">
          <ul className="plain">
            {Object.entries(result.post).map(([k, c]) => <li key={k}>{STEP_TEXT[k]?.(c) ?? `${k}: ${JSON.stringify(c)}`}</li>)}
          </ul>
        </Panel>
      )}
      {badBytes > 0 && (
        <div className="alert info"><b>NOTE</b>
          {human(badBytes)} of the drive could not be read. Files that touch those areas end in "_badsectors" and
          may show grey or broken parts.
        </div>
      )}
      {result.lost_volumes.length > 0 && (
        <div className="alert info"><b>INTEL</b>
          Found {result.lost_volumes.length} volume(s) the partition table does not point to (deleted or lost
          partitions): {result.lost_volumes.map((v) => `${v.fs} ${human(v.size)}`).join(", ")}.
        </div>
      )}
      <p className="dim small">A full list with offsets and checksums is in report.csv inside the folder.</p>
    </Step>
  );
}
