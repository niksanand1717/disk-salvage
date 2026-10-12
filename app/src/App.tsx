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
const RECOVER_STEPS: { id: StepId; label: string }[] = [
  { id: "source", label: "Source" }, { id: "check", label: "Check" }, { id: "image", label: "Copy" },
  { id: "recover", label: "Recover" }, { id: "finish", label: "Finish" },
];
const IMAGE_STEPS: { id: StepId; label: string }[] = [
  { id: "source", label: "Drive" }, { id: "image", label: "Copy" },
];

export function App() {
  const [mode, setMode] = useState<Mode | null>(null);
  const [step, setStep] = useState<StepId>("mode");
  const [source, setSource] = useState<Source | null>(null);
  const [image, setImage] = useState<ImageResult | null>(null);
  const [result, setResult] = useState<RecoverResult | null>(null);
  const [askPassword, setAskPassword] = useState<boolean | null>(null);

  useEffect(() => {
    void window.salvage.needsPassword().then(setAskPassword, () => setAskPassword(false));
  }, []);

  if (askPassword === null) return null;
  if (askPassword) {
    return <div className="app single"><main><PasswordStep onDone={() => setAskPassword(false)} /></main></div>;
  }

  const steps = mode === "image" ? IMAGE_STEPS
    : RECOVER_STEPS.filter((s) => s.id !== "image" || source?.isDrive !== false);
  const from = image ? image.path : source?.path ?? "";
  const fromLabel = image ? `the copy (${image.path})` : source?.label ?? "";

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
      <nav className="steps" aria-label="progress through the steps">
        <button className="brand" onClick={restart} disabled={step === "mode"}>
          <img src="logo.svg" alt="" width={28} height={28} />Disk Salvage
        </button>
        {mode && (
          <ol>
            {steps.map((s) => <li key={s.id} className={s.id === step ? "current" : ""}>{s.label}</li>)}
          </ol>
        )}
      </nav>
      <main>
        {step === "mode" && <ModeStep onPick={(m) => { setMode(m); setStep("source"); }} />}
        {step === "source" && (
          <SourceStep drivesOnly={mode === "image"} onPick={pickSource} onBack={restart} />
        )}
        {step === "check" && source && (
          <CheckStep source={source} onBack={() => setStep("source")}
                     onNext={() => setStep(source.isDrive ? "image" : "recover")} />
        )}
        {step === "image" && source && (
          <ImageStep source={source} standalone={mode === "image"}
                     onBack={() => setStep(mode === "image" ? "source" : "check")}
                     onFinish={restart}
                     onNext={(img) => { setMode("recover"); setImage(img); setStep("recover"); }} />
        )}
        {step === "recover" && source && (
          <RecoverStep from={from} label={fromLabel}
                       onBack={() => setStep(source.isDrive ? "image" : "check")}
                       onDone={(r) => { setResult(r); setStep("finish"); }} />
        )}
        {step === "finish" && result && <FinishStep result={result} onRestart={restart} />}
      </main>
    </div>
  );
}
