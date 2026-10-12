import { useEffect, useState } from "react";

import type { ImageResult, RecoverResult } from "./shared/protocol";
import { CheckStep } from "./steps/CheckStep";
import { FinishStep } from "./steps/FinishStep";
import { ImageStep } from "./steps/ImageStep";
import { ModeStep, type Mode } from "./steps/ModeStep";
import { PasswordStep } from "./steps/PasswordStep";
import { RecoverStep } from "./steps/RecoverStep";
import { SourceStep, type Source } from "./steps/SourceStep";

type StepId = "mode" | "source" | "check" | "image" | "recover" | "finish";
interface StepDef { id: StepId; label: string }
const RECOVER_STEPS: StepDef[] = [
  { id: "source", label: "Source" }, { id: "check", label: "Recon" }, { id: "image", label: "Capture" },
  { id: "recover", label: "Extract" }, { id: "finish", label: "Debrief" },
];
const IMAGE_STEPS: StepDef[] = [{ id: "source", label: "Target drive" }, { id: "image", label: "Capture" }];
const OPERATION: Record<Mode, string> = { recover: "Photo & video recovery", image: "Drive capture" };

function useClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now.toLocaleTimeString([], { hour12: false });
}

export function App() {
  const [mode, setMode] = useState<Mode | null>(null);
  const [step, setStep] = useState<StepId>("mode");
  const [source, setSource] = useState<Source | null>(null);
  const [image, setImage] = useState<ImageResult | null>(null);
  const [result, setResult] = useState<RecoverResult | null>(null);
  const [askPassword, setAskPassword] = useState<boolean | null>(null);
  const [elevated, setElevated] = useState<boolean | null>(null);
  const clock = useClock();

  useEffect(() => {
    void window.salvage.needsPassword().then(setAskPassword, () => setAskPassword(false));
  }, []);
  useEffect(() => {
    if (askPassword === false) void window.salvage.isElevated().then(setElevated, () => setElevated(false));
  }, [askPassword]);

  if (askPassword === null) return null;
  if (askPassword) {
    return (
      <div className="app single">
        <main>
          <div className="solo-brand"><img src="logo-small.svg" alt="" width={34} height={34} />Disk Salvage</div>
          <PasswordStep onDone={() => setAskPassword(false)} />
        </main>
      </div>
    );
  }

  const steps = mode === "image" ? IMAGE_STEPS
    : RECOVER_STEPS.filter((s) => s.id !== "image" || source?.isDrive !== false);
  const currentIdx = steps.findIndex((s) => s.id === step);
  const from = image ? image.path : source?.path ?? "";
  const fromLabel = image ? `the copy (${image.path})` : source?.label ?? "";
  const code = (id: StepId) => {
    const i = steps.findIndex((s) => s.id === id);
    return i >= 0 ? String(i + 1).padStart(2, "0") : undefined;
  };

  function restart() {
    setMode(null);
    setSource(null);
    setImage(null);
    setResult(null);
    setStep("mode");
  }

  function pickSource(s: Source) {
    setSource(s);
    setImage(null);
    setStep(mode === "image" ? "image" : "check");
  }

  return (
    <div className="app">
      <nav className="rail" aria-label="steps">
        <button className="brand" onClick={restart} disabled={step === "mode"} title="Back to the start">
          <img src="logo-small.svg" alt="" width={34} height={34} />
          <span>Disk Salvage<small>ops console</small></span>
        </button>
        {mode && (
          <div>
            <div className="rail-label">Sequence</div>
            <ol>
              {steps.map((s, i) => (
                <li key={s.id} className={i === currentIdx ? "current" : i < currentIdx ? "done" : ""}
                    aria-current={i === currentIdx ? "step" : undefined}>
                  <span className="n">{String(i + 1).padStart(2, "0")}</span>{s.label}
                </li>
              ))}
            </ol>
          </div>
        )}
        <div className="rail-status">
          <div><span className="led green" />Engine online</div>
          <div><span className={`led ${elevated ? "green" : "amber"}`} />
            {elevated ? "Admin access" : "Limited access"}</div>
          <div className="dim">{window.salvage.platform} · read-only</div>
        </div>
      </nav>
      <header className="topbar">
        <span className="op">Operation: <b>{mode ? OPERATION[mode] : "Standby"}</b></span>
        <span className="clock">{clock}</span>
      </header>
      <main>
        {step === "mode" && <ModeStep onPick={(m) => { setMode(m); setStep("source"); }} />}
        {step === "source" && (
          <SourceStep code={code("source")} drivesOnly={mode === "image"} onPick={pickSource} onBack={restart} />
        )}
        {step === "check" && source && (
          <CheckStep code={code("check")} source={source} onBack={() => setStep("source")}
                     onNext={() => setStep(source.isDrive ? "image" : "recover")} />
        )}
        {step === "image" && source && (
          <ImageStep code={code("image")} source={source} standalone={mode === "image"}
                     onBack={() => setStep(mode === "image" ? "source" : "check")}
                     onFinish={restart}
                     onNext={(img) => { setMode("recover"); setImage(img); setStep("recover"); }} />
        )}
        {step === "recover" && source && (
          <RecoverStep code={code("recover")} from={from} label={fromLabel}
                       onBack={() => setStep(source.isDrive ? "image" : "check")}
                       onDone={(r) => { setResult(r); setStep("finish"); }} />
        )}
        {step === "finish" && result && <FinishStep code={code("finish")} result={result} onRestart={restart} />}
      </main>
    </div>
  );
}
