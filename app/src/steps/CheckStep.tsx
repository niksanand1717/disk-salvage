import { useEffect, useState } from "react";

import { JobPanel, Panel, Readout, Step } from "../components";
import { human } from "../format";
import type { AnalyzeResult } from "../shared/protocol";
import { useJob } from "../useJob";
import type { Source } from "./SourceStep";

export function CheckStep({ code, source, onBack, onNext }:
    { code?: string; source: Source; onBack: () => void; onNext: () => void }) {
  const job = useJob();
  const [report, setReport] = useState<AnalyzeResult | null>(null);

  useEffect(() => {
    void job.run("analyze", { source: source.path }).then(setReport);
  }, [source.path]);

  const fsNames = report?.volumes.map((v) => v.fs?.name).filter(Boolean) ?? [];
  return (
    <Step code={code} title="Reconnaissance"
          intro={`Reading the partition table and file systems of ${source.label}.`}
          footer={<>
            <button className="ghost" onClick={onBack}>Back</button>
            <button onClick={onNext} disabled={job.state.running}>Continue ▸</button>
          </>}>
      {job.state.running && <JobPanel state={job.state} showMap={false} />}
      {!job.state.running && job.state.error != null && <JobPanel state={job.state} showMap={false} />}
      {report && (
        <>
          <Panel label="Assessment" right={<><span className="led green" />scan complete</>}>
            <div className="readouts">
              <Readout label="Size" value={human(report.size)} />
              <Readout label="Volumes" value={report.volumes.length} />
              <Readout label="File systems" value={fsNames.length ? fsNames.join(", ") : "none found"}
                       tone={fsNames.length ? undefined : "err"} />
              <Readout label="Unreadable" value={report.bad_ranges.length
                         ? `${report.bad_ranges.length} area${report.bad_ranges.length === 1 ? "" : "s"}` : "none"}
                       tone={report.bad_ranges.length ? "err" : "ok"} />
            </div>
            <div>
              <div className="verdict-head">▸ Verdict</div>
              <div className="verdict">{report.verdict}</div>
            </div>
          </Panel>
          <Panel label="Technical details">
            <details>
              <summary>Show full report</summary>
              <pre className="report">{report.lines.join("\n")}</pre>
            </details>
          </Panel>
        </>
      )}
    </Step>
  );
}
