import { useState } from "react";
import { Check, Bot, Smartphone, Radio, ArrowRight, Loader2, Eye, EyeOff, ListChecks, Rocket, MessageSquare, Sparkles } from "lucide-react";
import { markOnboardingComplete, getToken, clearAuth } from "../api/auth";
import { cn } from "../lib/utils";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

function authHeaders() {
  return { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` };
}

async function api(method: string, path: string, body?: object) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Request failed");
  return data;
}

// ---------------------------------------------------------------------------
// Step indicators
// ---------------------------------------------------------------------------

const STEPS = [
  { icon: Bot,        label: "Acquisition" },
  { icon: Smartphone, label: "Conversion"  },
  { icon: Radio,      label: "Signals"     },
];

function StepDots({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-2 justify-center mb-8">
      {STEPS.map((s, i) => {
        const Icon = s.icon;
        const done = i < current;
        const active = i === current;
        return (
          <div key={i} className="flex items-center gap-2">
            <div className={cn(
              "h-8 w-8 rounded-full flex items-center justify-center transition-all",
              done   ? "bg-primary text-primary-foreground" :
              active ? "bg-primary/15 text-primary ring-2 ring-primary/40" :
                       "bg-secondary text-muted-foreground"
            )}>
              {done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : <Icon className="h-3.5 w-3.5" />}
            </div>
            {i < STEPS.length - 1 && (
              <div className={cn("h-px w-8", done ? "bg-primary" : "bg-border")} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Bot token
// ---------------------------------------------------------------------------

function StepBot({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const [token, setToken] = useState("");
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!token.trim()) return;
    setLoading(true); setError(null);
    try {
      await api("PATCH", "/settings/bot/credentials", { bot_token: token.trim() });
      await api("POST", "/settings/bot/register-webhook");
      onDone();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Connect your Acquisition Bot</h2>
        <p className="text-sm text-muted-foreground mt-1">
          This is the bot your ad traffic lands in. Every click from your ads DMs this bot first — we capture them into the CRM automatically. Create one via BotFather if you haven't already.
        </p>
      </div>

      <div className="surface-card p-4 space-y-2 text-xs text-muted-foreground">
        <p className="eyebrow text-foreground">How to get your token</p>
        <ol className="list-decimal list-inside space-y-1 leading-relaxed">
          <li>Open Telegram and search <span className="font-mono text-foreground">@BotFather</span></li>
          <li>Send <span className="font-mono text-foreground">/newbot</span> and follow the prompts</li>
          <li>Copy the token BotFather gives you and paste it below</li>
        </ol>
      </div>

      <div>
        <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Bot Token</label>
        <div className="relative mt-1.5">
          <input
            type={show ? "text" : "password"}
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder="123456789:ABCDef-ghijklmnop"
            className="w-full px-3 py-2.5 pr-10 rounded-xl bg-secondary text-[13px] text-foreground font-mono outline-none placeholder:text-muted-foreground/40"
          />
          <button
            type="button"
            onClick={() => setShow(s => !s)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {error && <p className="text-[12px] text-destructive">{error}</p>}

      <button
        onClick={handleSubmit}
        disabled={!token.trim() || loading}
        className="w-full py-3 rounded-xl bg-primary text-primary-foreground text-[14px] font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Save & continue</span><ArrowRight className="h-4 w-4" /></>}
      </button>

      <button onClick={onSkip} className="w-full text-[12px] text-muted-foreground text-center py-1">
        Set up later
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Conversion Desk (Telethon)
// ---------------------------------------------------------------------------

type TelethonStep = "phone" | "otp";

function StepTelethon({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const [phase, setPhase] = useState<TelethonStep>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [phoneCodeHash, setPhoneCodeHash] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePhone() {
    if (!phone.trim()) return;
    setLoading(true); setError(null);
    try {
      const res = await api("POST", "/settings/telethon/connect", { phone: phone.trim() });
      setPhoneCodeHash(res?.phone_code_hash || "");
      setPhase("otp");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleOtp() {
    if (!code.trim()) return;
    setLoading(true); setError(null);
    try {
      await api("POST", "/settings/telethon/verify", {
        phone: phone.trim(),
        code: code.trim(),
        phone_code_hash: phoneCodeHash,
      });
      onDone();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Connect your Conversion Desk</h2>
        <p className="text-sm text-muted-foreground mt-1">
          This is your personal Telegram account — the human on the other side that replies to leads and closes them. Use the number linked to your eSIM (separate from your personal account).
        </p>
      </div>

      {phase === "phone" ? (
        <>
          <div>
            <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Phone number</label>
            <input
              type="tel"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="+44 7700 900000"
              className="mt-1.5 w-full px-3 py-2.5 rounded-xl bg-secondary text-[13px] text-foreground outline-none placeholder:text-muted-foreground/40"
            />
          </div>
          {error && <p className="text-[12px] text-destructive">{error}</p>}
          <button
            onClick={handlePhone}
            disabled={!phone.trim() || loading}
            className="w-full py-3 rounded-xl bg-primary text-primary-foreground text-[14px] font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Send code</span><ArrowRight className="h-4 w-4" /></>}
          </button>
        </>
      ) : (
        <>
          <div className="ios-card p-3 text-[13px] text-muted-foreground">
            Code sent to <span className="text-foreground font-medium">{phone}</span>. Check your Telegram app.
          </div>
          <div>
            <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">5-digit code</label>
            <input
              type="text"
              inputMode="numeric"
              maxLength={5}
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, ""))}
              placeholder="12345"
              className="mt-1.5 w-full px-3 py-2.5 rounded-xl bg-secondary text-[13px] text-foreground font-mono tracking-widest text-center outline-none placeholder:text-muted-foreground/40"
            />
          </div>
          {error && <p className="text-[12px] text-destructive">{error}</p>}
          <button
            onClick={handleOtp}
            disabled={code.length < 5 || loading}
            className="w-full py-3 rounded-xl bg-primary text-primary-foreground text-[14px] font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Verify & continue</span><ArrowRight className="h-4 w-4" /></>}
          </button>
          <button onClick={() => setPhase("phone")} className="w-full text-[12px] text-muted-foreground text-center">
            Wrong number? Go back
          </button>
        </>
      )}

      <button onClick={onSkip} className="w-full text-[12px] text-muted-foreground text-center py-1">
        Set up later
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Signals channel
// ---------------------------------------------------------------------------

type DetectedChannel = { id: number; chat_id: string; title: string | null };

function StepChannel({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const [channelId, setChannelId] = useState("");
  const [detected, setDetected] = useState<DetectedChannel[]>([]);
  const [detecting, setDetecting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDetect() {
    setDetecting(true); setError(null);
    try {
      const rows: DetectedChannel[] = await api("GET", "/settings/my/pending-channels");
      setDetected(rows);
      if (rows.length === 0) {
        setError("No channels detected yet. Make sure your bot is added as an ADMIN (not just a member) and try again in a few seconds.");
      } else if (rows.length === 1) {
        // Auto-fill if there's only one
        setChannelId(rows[0].chat_id);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setDetecting(false);
    }
  }

  async function handleSubmit() {
    if (!channelId.trim()) return;
    setLoading(true); setError(null);
    try {
      await api("PATCH", "/affiliate/me/checklist", { vip_channel_id: channelId.trim() });
      onDone();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Link your Signals Channel</h2>
        <p className="text-sm text-muted-foreground mt-1">
          The private channel your paying members get. Trade signals forward here automatically — add your Acquisition Bot as admin and we'll detect it.
        </p>
      </div>

      <div className="surface-card p-4 space-y-2 text-xs text-muted-foreground">
        <p className="eyebrow text-foreground">How it works</p>
        <ol className="list-decimal list-inside space-y-1 leading-relaxed">
          <li>Open your private Signals channel (the one your paid members will join)</li>
          <li>Go to <span className="text-foreground font-medium">Channel settings → Administrators → Add admin</span></li>
          <li>Search for <span className="font-medium text-foreground">the bot you created in step 1</span> and add it as admin (with permission to post messages)</li>
          <li>Come back here and click <span className="font-medium text-foreground">Detect channel</span> below</li>
        </ol>
      </div>

      {/* Detected channels picker */}
      {detected.length > 0 && (
        <div className="space-y-1.5">
          <p className="eyebrow">Detected</p>
          <div className="space-y-1.5">
            {detected.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setChannelId(c.chat_id)}
                className={cn(
                  "w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors",
                  channelId === c.chat_id
                    ? "border-primary bg-primary/10"
                    : "border-border bg-secondary/40 hover:bg-secondary/70"
                )}
              >
                <div className="min-w-0">
                  <p className="text-sm text-foreground truncate">{c.title || c.chat_id}</p>
                  <p className="text-[11px] text-muted-foreground font-mono truncate">{c.chat_id}</p>
                </div>
                {channelId === c.chat_id && <Check className="h-4 w-4 text-primary shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}

      <button
        onClick={handleDetect}
        disabled={detecting}
        className="w-full h-10 rounded-lg border border-border bg-secondary/40 hover:bg-secondary/70 text-sm font-semibold text-foreground transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
      >
        {detecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Detect channel</>}
      </button>

      {/* Manual fallback */}
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer hover:text-foreground transition-colors">Or enter the channel ID manually</summary>
        <div className="mt-2 space-y-1.5">
          <input
            type="text"
            value={channelId}
            onChange={e => setChannelId(e.target.value)}
            placeholder="-1001234567890"
            className="w-full h-9 px-3 rounded-lg bg-secondary/60 border border-border text-xs text-foreground font-mono outline-none placeholder:text-muted-foreground/50 focus:border-primary focus:ring-2 focus:ring-primary/20 transition-colors"
          />
          <p className="text-[11px] leading-relaxed">
            Forward any message from the channel to <span className="font-mono text-foreground">@getidsbot</span> in a DM — it replies with the ID.
          </p>
        </div>
      </details>

      {error && <p className="text-xs text-destructive leading-relaxed">{error}</p>}

      <button
        onClick={handleSubmit}
        disabled={!channelId.trim() || loading}
        className="w-full h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50 flex items-center justify-center gap-2 hover:bg-primary/90 transition-colors"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Finish setup</span><Check className="h-4 w-4" strokeWidth={3} /></>}
      </button>

      <button onClick={onSkip} className="w-full text-xs text-muted-foreground hover:text-foreground text-center py-1 transition-colors">
        Set up later
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main onboarding page
// ---------------------------------------------------------------------------

type Phase = "intro" | "setup" | "done";

function IntroScreen({ onStart }: { onStart: () => void }) {
  const items = [
    { icon: Bot,        title: "Acquisition Bot",  body: "Captures people who click your ads. You'll create a bot via @BotFather and paste the token." },
    { icon: Smartphone, title: "Conversion Desk",  body: "Your personal Telegram account — the human who replies to leads and closes them." },
    { icon: Radio,      title: "Signals Channel",  body: "The private channel your paying members get. Trade signals forward here automatically." },
  ];
  return (
    <div className="space-y-5">
      <div className="text-center">
        <div className="h-10 w-10 rounded-xl bg-primary/15 flex items-center justify-center mx-auto mb-2">
          <Rocket className="h-5 w-5 text-primary" />
        </div>
        <h2 className="text-[18px] font-bold text-foreground">Let's get you live</h2>
        <p className="text-[13px] text-muted-foreground mt-1">3 quick steps to connect your workspace. Takes about 5 minutes.</p>
      </div>

      <div className="space-y-3">
        {items.map(({ icon: Icon, title, body }, i) => (
          <div key={title} className="flex gap-3">
            <div className="h-7 w-7 rounded-lg bg-secondary flex items-center justify-center shrink-0">
              <Icon className="h-3.5 w-3.5 text-muted-foreground" />
            </div>
            <div className="flex-1">
              <p className="text-[13px] font-semibold text-foreground">Step {i + 1} — {title}</p>
              <p className="text-[12px] text-muted-foreground leading-relaxed">{body}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-xl bg-secondary/60 p-3 space-y-1">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <p className="text-[12px] font-semibold text-foreground">Once you're done</p>
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Your dashboard shows a full 9-step checklist for the rest: eSIM, free/tutorial channels,
          sales scripts, PU Prime IB, Meta Pixel, ads. You can tackle those at your own pace —
          they don't block the CRM.
        </p>
      </div>

      <button
        onClick={onStart}
        className="w-full py-3 rounded-xl bg-primary text-primary-foreground text-[14px] font-semibold flex items-center justify-center gap-2"
      >
        <span>Start setup</span><ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}

function DoneScreen({ completing }: { completing: boolean }) {
  const nextUp = [
    { icon: Smartphone, title: "Get an eSIM or second phone",  body: "Keeps your Conversion Desk separate from your personal number." },
    { icon: Radio,      title: "Launch your free channel",    body: "Post daily content + a link to your Acquisition Bot. Drives the top of your funnel." },
    { icon: MessageSquare, title: "Load sales scripts",        body: "Save them as Telegram quick replies so you can reply to leads fast." },
    { icon: ListChecks, title: "Finish the dashboard checklist", body: "9 items total — tutorial channel, PU Prime IB, Meta Pixel, ads." },
  ];
  return (
    <div className="space-y-5">
      <div className="text-center">
        <div className="h-12 w-12 rounded-full bg-stage-deposited/15 flex items-center justify-center mx-auto mb-2">
          <Check className="h-6 w-6 text-stage-deposited" strokeWidth={3} />
        </div>
        <h2 className="text-[18px] font-bold text-foreground">You're live</h2>
        <p className="text-[13px] text-muted-foreground mt-1">
          Leads from your ads now flow into your CRM and signals will forward to your Signals Channel automatically.
        </p>
      </div>

      <div>
        <p className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider mb-2">What's next</p>
        <div className="ios-card divide-y divide-[hsl(var(--ios-separator))]">
          {nextUp.map(({ icon: Icon, title, body }) => (
            <div key={title} className="flex gap-3 p-3">
              <div className="h-7 w-7 rounded-lg bg-secondary flex items-center justify-center shrink-0">
                <Icon className="h-3.5 w-3.5 text-muted-foreground" />
              </div>
              <div className="flex-1">
                <p className="text-[12px] font-semibold text-foreground">{title}</p>
                <p className="text-[11px] text-muted-foreground leading-relaxed">{body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {completing ? (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Taking you to your dashboard…
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground text-center">Redirecting to your dashboard…</p>
      )}
    </div>
  );
}

export default function OnboardingPage() {
  const [phase, setPhase] = useState<Phase>("intro");
  const [step, setStep] = useState(0);
  const [completing, setCompleting] = useState(false);

  async function finish() {
    setPhase("done");
    setCompleting(true);
    try {
      await api("POST", "/settings/onboarding/complete");
    } catch { /* non-fatal */ }
    markOnboardingComplete();
    // Give the user a beat to read the "what's next" screen
    setTimeout(() => { window.location.href = "/"; }, 3500);
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col items-center justify-center px-4 py-12 page-enter">
      <div className="w-full max-w-sm">

        {/* Logo / brand */}
        <div className="text-center mb-8">
          <div className="h-11 w-11 rounded-xl bg-primary/15 border border-primary/20 flex items-center justify-center mx-auto mb-3">
            <svg viewBox="0 0 24 24" className="h-5 w-5 text-primary" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-foreground tracking-tight">Welcome to Telelytics</h1>
          {phase === "intro" && <p className="text-sm text-muted-foreground mt-1">Let's get your workspace live.</p>}
          {phase === "setup" && <p className="text-sm text-muted-foreground mt-1">Step {step + 1} of 3</p>}
          {phase === "done"  && <p className="text-sm text-muted-foreground mt-1">Setup complete</p>}
        </div>

        {phase === "setup" && <StepDots current={step} />}

        <div className="surface-card p-6">
          {phase === "intro" && <IntroScreen onStart={() => setPhase("setup")} />}
          {phase === "setup" && step === 0 && <StepBot onDone={() => setStep(1)} onSkip={() => setStep(1)} />}
          {phase === "setup" && step === 1 && <StepTelethon onDone={() => setStep(2)} onSkip={() => setStep(2)} />}
          {phase === "setup" && step === 2 && <StepChannel onDone={finish} onSkip={finish} />}
          {phase === "done"  && <DoneScreen completing={completing} />}
        </div>

        <button
          onClick={() => { clearAuth(); window.location.href = "/login"; }}
          className="mt-6 w-full text-xs text-muted-foreground hover:text-foreground text-center transition-colors"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
