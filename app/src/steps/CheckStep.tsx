import { useEffect, useState } from "react";

import { JobPanel, Step } from "../components";
import type { AnalyzeResult } from "../shared/protocol";
import { useJob } from "../useJob";
import type { Source } from "./SourceStep";

export function CheckStep({ source, onBack, onNext }: { source: Source; onBack: () => void; onNext: () => void }) {
  const job = useJob();
  const [report, setReport] = useState<AnalyzeResult | null>(null);

  useEffect(() => {
    void job.run("analyze", { source: source.path }).then(setReport);
  }, [source.path]);

  return (
    <Step title="Checking the drive"
          intro={`Reading the partition table and filesystems of ${source.label}.`}
          footer={<>
            <button className="ghost" onClick={onBack}>Back</button>
            <button onClick={onNext} disabled={job.state.running}>Continue</button>
          </>}>
      <JobPanel state={job.state} />
      {report && (
        <>
          <div className="box verdict">{report.verdict}</div>
          <details>
            <summary>Technical details</summary>
            <pre className="report">{report.lines.join("\n")}</pre>
          </details>
        </>
      )}
    </Step>
  );
}
