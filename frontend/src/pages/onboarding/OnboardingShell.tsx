import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import Step1Account from "./Step1Account";
import Step2Organization from "./Step2Organization";
import Step3Pipeline from "./Step3Pipeline";
import Step4Telegram from "./Step4Telegram";
import Step5Integrations from "./Step5Integrations";
import Step6Review from "./Step6Review";
import { markOnboardingComplete, getStoredUser, getToken, clearAuth } from "../../api/auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

const STEPS = ["Account", "Organization", "Pipeline", "Telegram", "Integrations", "Review"];
const KEY = "onboard_step";

export default function OnboardingShell() {
  const [step, setStep] = useState<number>(() => {
    const raw = localStorage.getItem(KEY);
    const n = raw ? Number(raw) : 0;
    return Number.isFinite(n) ? Math.min(STEPS.length - 1, Math.max(0, n)) : 0;
  });
  const [completing, setCompleting] = useState(false);

  useEffect(() => { localStorage.setItem(KEY, String(step)); }, [step]);

  const next = () => setStep((s) => Math.min(STEPS.length - 1, s + 1));
  const back = () => setStep((s) => Math.max(0, s - 1));
  const skip = () => next();

  const finish = async () => {
    setCompleting(true);
    try {
      await fetch(`${API_BASE}/settings/onboarding/complete`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
      });
    } catch { /* non-fatal */ }
    markOnboardingComplete();
    localStorage.removeItem(KEY);
    setTimeout(() => { window.location.href = "/"; }, 600);
  };

  const user = getStoredUser();

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col items-center px-4 py-12">
      <div className="w-full max-w-xl">
        <div className="flex items-center gap-2 mb-8">
          {STEPS.map((label, i) => (
            <div key={label} className="flex-1">
              <div className="flex items-center gap-2">
                <div className={`h-7 w-7 rounded-full grid place-items-center text-[11px] font-semibold transition-colors
                  ${i < step ? "bg-primary text-primary-foreground"
                  : i === step ? "bg-primary/15 text-primary ring-2 ring-primary/40"
                  : "bg-secondary text-muted-foreground"}`}>
                  {i < step ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
                </div>
                {i < STEPS.length - 1 && (
                  <div className={`flex-1 h-px ${i < step ? "bg-primary" : "bg-border"}`} />
                )}
              </div>
              <p className="text-[10px] text-muted-foreground mt-1">{label}</p>
            </div>
          ))}
        </div>

        <div className="surface-card p-6">
          {step === 0 && <Step1Account user={user} onNext={next} />}
          {step === 1 && <Step2Organization onNext={next} onBack={back} onSkip={skip} />}
          {step === 2 && <Step3Pipeline onNext={next} onBack={back} onSkip={skip} />}
          {step === 3 && <Step4Telegram onNext={next} onBack={back} onSkip={skip} />}
          {step === 4 && <Step5Integrations onNext={next} onBack={back} onSkip={skip} />}
          {step === 5 && <Step6Review onFinish={finish} onBack={back} completing={completing} />}
        </div>

        <button
          onClick={() => { clearAuth(); window.location.href = "/login"; }}
          className="mt-6 w-full text-xs text-muted-foreground hover:text-foreground text-center transition-colors">
          Sign out
        </button>
      </div>
    </div>
  );
}
