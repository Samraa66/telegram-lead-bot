import { useState } from "react";
import { Eye, EyeOff, ArrowRight, Loader2, Check } from "lucide-react";
import { getToken, getStoredUser } from "../../api/auth";

interface StepProps {
  onDone: () => void;
  onSkip: () => void;
}

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
// Step 1 — Bot token
// ---------------------------------------------------------------------------

export function StepBot({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
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

export function StepTelethon({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
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
// Step — Channel (branched by org_role)
//   org_owner       → set source_channel_id (the org's signal feed)
//   workspace_owner → set vip_channel_id (sub-affiliate's destination channel)
// ---------------------------------------------------------------------------

export function StepChannel({ onDone, onSkip }: StepProps) {
  const user = getStoredUser();
  if (user?.org_role === "org_owner") {
    return <StepSourceChannel onDone={onDone} onSkip={onSkip} />;
  }
  return <StepVipChannel onDone={onDone} onSkip={onSkip} />;
}

function StepSourceChannel({ onDone, onSkip }: StepProps) {
  const [channelId, setChannelId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!channelId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await api("PATCH", "/workspace/me/source-channel", { source_channel_id: channelId.trim() });
      onDone();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">Connect your Signal Source channel</h3>
        <p className="text-[13px] text-muted-foreground mt-1">
          The Telegram channel where your trade signals are posted. Each new post here will be
          mirrored to every active affiliate's VIP channel automatically. Your Telegram user must
          be a member or admin of this channel.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-secondary/40 p-3 space-y-1.5 text-[12px] text-muted-foreground">
        <p className="font-medium text-foreground">How to find the channel ID</p>
        <ol className="list-decimal list-inside space-y-1 leading-relaxed">
          <li>Open the channel in Telegram</li>
          <li>Forward any message from it to <span className="text-foreground">@RawDataBot</span> — it returns the channel's ID (starts with <code>-100</code>)</li>
          <li>Or paste the public <code>@username</code> if it's a public channel</li>
        </ol>
      </div>

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Source channel ID or @username</label>
        <input
          value={channelId}
          onChange={(e) => setChannelId(e.target.value)}
          placeholder="-1001234567890 or @yoursignals"
          className="w-full px-3 py-2 rounded-lg border border-border bg-secondary/40 text-sm"
        />
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={loading || !channelId.trim()}
          onClick={handleSubmit}
          className="flex-1 h-9 rounded-lg bg-primary text-primary-foreground text-xs font-medium disabled:opacity-50 flex items-center justify-center gap-1.5"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Save and continue</span><ArrowRight className="h-4 w-4" /></>}
        </button>
        <button onClick={onSkip} className="px-3 h-9 rounded-lg border border-border text-xs text-muted-foreground hover:text-foreground transition-colors">
          Skip
        </button>
      </div>
    </div>
  );
}

interface DetectedChannel { id: number; chat_id: string; title: string | null }

function StepVipChannel({ onDone, onSkip }: StepProps) {
  const parentBotUsername = getStoredUser()?.parent_bot_username;
  const botLabel = parentBotUsername ? `@${parentBotUsername}` : "your sponsor's bot";

  const [channelId, setChannelId] = useState("");
  const [detected, setDetected] = useState<DetectedChannel[]>([]);
  const [detecting, setDetecting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDetect() {
    setDetecting(true);
    setError(null);
    try {
      const rows: DetectedChannel[] = await api("GET", "/settings/my/pending-channels");
      setDetected(rows);
      if (rows.length === 0) {
        setError(`No channels detected yet. Make sure ${botLabel} is added as an ADMIN (not just a member) and try again in a few seconds.`);
      } else if (rows.length === 1) {
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
    setLoading(true);
    setError(null);
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
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">Link your VIP channel</h3>
        <p className="text-[13px] text-muted-foreground mt-1">
          The private channel your paying members get. Trade signals will be forwarded here automatically.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-secondary/40 p-3 space-y-1.5 text-[12px] text-muted-foreground">
        <p className="font-medium text-foreground">How it works</p>
        <ol className="list-decimal list-inside space-y-1 leading-relaxed">
          <li>Open your private VIP channel (the one your paid members will join)</li>
          <li>Go to <span className="text-foreground">Channel settings → Administrators → Add admin</span></li>
          <li>Search for <span className="font-medium text-foreground">{botLabel}</span> and add it as admin (with permission to post messages)</li>
          <li>Come back here and click <span className="text-foreground">Detect channel</span> below</li>
        </ol>
      </div>

      {detected.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Detected</p>
          <div className="space-y-1.5">
            {detected.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setChannelId(c.chat_id)}
                className={`w-full flex items-center justify-between gap-3 px-3 py-2 rounded-lg border text-left transition-colors ${
                  channelId === c.chat_id
                    ? "border-primary bg-primary/10"
                    : "border-border bg-secondary/40 hover:bg-secondary/70"
                }`}
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

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Or paste channel ID manually</label>
        <input
          value={channelId}
          onChange={(e) => setChannelId(e.target.value)}
          placeholder="-1001234567890"
          className="w-full px-3 py-2 rounded-lg border border-border bg-secondary/40 text-sm"
        />
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleDetect}
          disabled={detecting}
          className="px-3 h-9 rounded-lg border border-border text-xs hover:bg-secondary/40 transition-colors disabled:opacity-50"
        >
          {detecting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Detect channel"}
        </button>
        <button
          type="button"
          disabled={loading || !channelId.trim()}
          onClick={handleSubmit}
          className="flex-1 h-9 rounded-lg bg-primary text-primary-foreground text-xs font-medium disabled:opacity-50 flex items-center justify-center gap-1.5"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Save and continue</span><ArrowRight className="h-4 w-4" /></>}
        </button>
        <button onClick={onSkip} className="px-3 h-9 rounded-lg border border-border text-xs text-muted-foreground hover:text-foreground transition-colors">
          Skip
        </button>
      </div>
    </div>
  );
}
