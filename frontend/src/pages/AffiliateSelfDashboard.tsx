import { useEffect, useState, useCallback, useRef } from "react";
import {
  Copy, Check, Users, TrendingUp, DollarSign, Trophy,
  ChevronDown, ChevronUp, LogOut,
} from "lucide-react";
import { fetchMyProfile, updateMyChecklist, AffiliateProfile } from "../api/affiliateMe";
import { AffiliateChecklist } from "../api/affiliates";
import { clearAuth } from "../api/auth";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Checklist definition (same steps as admin view)
// ---------------------------------------------------------------------------

type ChecklistStep =
  | { kind: "bool"; key: keyof AffiliateChecklist; label: string; guide: string }
  | { kind: "channel"; idKey: keyof AffiliateChecklist; membersKey: keyof AffiliateChecklist; label: string; target: number; guide: string }
  | { kind: "text"; key: keyof AffiliateChecklist; label: string; placeholder: string; guide: string };

const STEPS: ChecklistStep[] = [
  {
    kind: "bool", key: "esim_done", label: "Secondary phone / eSIM",
    guide: "Get a second phone number or eSIM to keep this Telegram account separate from your personal one.",
  },
  {
    kind: "channel", idKey: "free_channel_id", membersKey: "free_channel_members",
    label: "Free Channel (public)", target: 2000,
    guide: "Create a PUBLIC Telegram channel. Daily content: 9am good morning, VIP profit screenshots, lifestyle, welcome new VIP members by name. Goal: drive people to your CTA button.",
  },
  {
    kind: "bool", key: "bot_setup_done", label: "CTA Button configured",
    guide: "Requires Telegram Business (~€8/mo):\n1. Create a personal chat link in Telegram Business\n2. @BotFather → /newbot (must end in 'bot')\n3. Add your bot + @ChannelHelperBot as admins in your free channel\n4. @ChannelHelperBot → Menu → Create Post → add button 'Click here' linking to your chat link\n5. Pin the post at the top",
  },
  {
    kind: "channel", idKey: "vip_channel_id", membersKey: "vip_channel_members",
    label: "VIP Channel (private)", target: 60,
    guide: "Create a PRIVATE Telegram channel. Once you enter the channel ID below, signals are forwarded automatically — you don't need to do anything else.",
  },
  {
    kind: "channel", idKey: "tutorial_channel_id", membersKey: "tutorial_channel_members",
    label: "Tutorial Channel (public)", target: 50,
    guide: "Create a PUBLIC channel with trading tutorial content for beginners. Disable content saving. Copy our tutorial lessons (we'll give you access). End with a link to request VIP access.",
  },
  {
    kind: "bool", key: "sales_scripts_done", label: "Sales scripts loaded",
    guide: "Load the sales scripts into your Telegram quick replies so you can respond to leads fast.",
  },
  {
    kind: "text", key: "ib_profile_id", label: "PU Prime IB Profile ID", placeholder: "e.g. IB-12345",
    guide: "Create your Introducing Broker account on PU Prime and paste your IB ID here. This is how your commissions are tracked.",
  },
  {
    kind: "bool", key: "pixel_setup_done", label: "Meta Pixel setup",
    guide: "Set up your Meta Pixel in Ads Manager so your ad conversions are tracked.",
  },
  {
    kind: "bool", key: "ads_live", label: "Ads running",
    guide: "Your funnel: Ads → Free Channel → CTA button → DM → Qualify → Tutorial → VIP",
  },
];

const TOTAL = STEPS.length;

function progress(aff: AffiliateChecklist): number {
  let done = 0;
  if (aff.esim_done) done++;
  if (aff.free_channel_id) done++;
  if (aff.bot_setup_done) done++;
  if (aff.vip_channel_id) done++;
  if (aff.tutorial_channel_id) done++;
  if (aff.sales_scripts_done) done++;
  if (aff.ib_profile_id) done++;
  if (aff.pixel_setup_done) done++;
  if (aff.ads_live) done++;
  return done;
}

// ---------------------------------------------------------------------------
// Copy button
// ---------------------------------------------------------------------------

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={copy}
      className={cn(
        "flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all",
        copied ? "bg-stage-deposited/15 text-stage-deposited" : "bg-secondary text-muted-foreground"
      )}
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : (label || "Copy")}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Single checklist step row
// ---------------------------------------------------------------------------

function StepRow({
  step, profile, onSave,
}: {
  step: ChecklistStep;
  profile: AffiliateProfile;
  onSave: (patch: Partial<AffiliateChecklist>) => void;
}) {
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const debouncedSave = (patch: Partial<AffiliateChecklist>) => {
    onSave(patch);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => updateMyChecklist(patch).catch(() => {}), 600);
  };

  const isDone = (() => {
    if (step.kind === "bool") return Boolean(profile[step.key]);
    if (step.kind === "channel") return Boolean(profile[step.idKey]);
    return Boolean(profile[step.key]);
  })();

  return (
    <div className="border-b border-[hsl(var(--ios-separator))] last:border-0">
      {/* Step header */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-4 py-3.5 text-left"
      >
        <span className={cn(
          "h-5 w-5 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors",
          isDone ? "bg-stage-deposited border-stage-deposited" : "border-muted-foreground/30"
        )}>
          {isDone && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
        </span>
        <span className={cn(
          "flex-1 text-[13px] font-medium",
          isDone ? "text-muted-foreground line-through" : "text-foreground"
        )}>
          {step.label}
        </span>
        {step.kind === "channel" && (
          <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">
            {(profile[step.membersKey] as number) || 0}/{step.target.toLocaleString()}
          </span>
        )}
        <span className="text-muted-foreground shrink-0">
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </span>
      </button>

      {/* Expanded */}
      {open && (
        <div className="px-4 pb-4 space-y-3">
          {/* Guide */}
          <p className="text-[12px] text-muted-foreground whitespace-pre-line leading-relaxed">
            {step.guide}
          </p>

          {/* Input */}
          {step.kind === "bool" && (
            <button
              onClick={() => debouncedSave({ [step.key]: !profile[step.key] } as Partial<AffiliateChecklist>)}
              className={cn(
                "px-4 py-2 rounded-xl text-[12px] font-semibold transition-colors",
                isDone
                  ? "bg-stage-deposited/15 text-stage-deposited"
                  : "bg-primary/15 text-primary"
              )}
            >
              {isDone ? "Mark as not done" : "Mark as done"}
            </button>
          )}

          {step.kind === "channel" && (
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">
                  Channel ID
                </label>
                <input
                  defaultValue={(profile[step.idKey] as string | null) || ""}
                  onBlur={(e) => debouncedSave({ [step.idKey]: e.target.value || null } as Partial<AffiliateChecklist>)}
                  placeholder="e.g. -1001234567890"
                  className="mt-1 w-full px-3 py-2 rounded-xl bg-secondary text-[12px] text-foreground outline-none placeholder:text-muted-foreground/40 font-mono"
                />
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">
                  Members (auto-synced hourly)
                </label>
                <div className="mt-1 flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full"
                      style={{ width: `${Math.min(100, ((profile[step.membersKey] as number || 0) / step.target) * 100)}%` }}
                    />
                  </div>
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {(profile[step.membersKey] as number || 0).toLocaleString()} / {step.target.toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          )}

          {step.kind === "text" && (
            <div>
              <input
                defaultValue={(profile[step.key] as string | null) || ""}
                onBlur={(e) => debouncedSave({ [step.key]: e.target.value || null } as Partial<AffiliateChecklist>)}
                placeholder={step.placeholder}
                className="w-full px-3 py-2 rounded-xl bg-secondary text-[12px] text-foreground outline-none placeholder:text-muted-foreground/40"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main affiliate dashboard
// ---------------------------------------------------------------------------

export default function AffiliateSelfDashboard() {
  const [profile, setProfile] = useState<AffiliateProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchMyProfile();
      setProfile(data);
    } catch (e: any) {
      setError(e?.message || "Failed to load your profile");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handlePatch = (patch: Partial<AffiliateChecklist>) => {
    setProfile((prev) => prev ? { ...prev, ...patch } : prev);
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Loading…
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="flex-1 flex items-center justify-center text-destructive text-sm px-4 text-center">
        {error || "Could not load profile"}
      </div>
    );
  }

  const done = progress(profile);
  const pct = Math.round((done / TOTAL) * 100);

  return (
    <div className="flex flex-col h-full bg-[hsl(var(--ios-grouped-bg))] overflow-y-auto">

      {/* Header */}
      <div className="bg-card/80 backdrop-blur-xl sticky top-0 z-10 px-4 pt-3 pb-3 flex items-center justify-between border-b border-[hsl(var(--ios-separator))]">
        <div>
          <p className="text-[15px] font-bold text-foreground">{profile.name}</p>
          <p className="text-[11px] text-muted-foreground">Affiliate Portal</p>
        </div>
        <button
          onClick={() => { clearAuth(); window.location.href = "/login"; }}
          className="p-2 text-muted-foreground"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>

      {/* Referral link */}
      <div className="px-4 pt-4">
        <div className="ios-card p-4 space-y-2">
          <p className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider">Your Referral Link</p>
          {profile.referral_link ? (
            <div className="flex items-center gap-2">
              <p className="flex-1 text-[12px] text-foreground font-mono truncate">{profile.referral_link}</p>
              <CopyButton text={profile.referral_link} label="Copy Link" />
            </div>
          ) : (
            <p className="text-[12px] text-muted-foreground">Referral tag: {profile.referral_tag}</p>
          )}
          <p className="text-[11px] text-muted-foreground">Share this everywhere. Every lead who clicks it is automatically attributed to you.</p>
        </div>
      </div>

      {/* Stats */}
      <div className="px-4 pt-3 grid grid-cols-4 gap-2">
        {[
          { icon: <Users className="h-4 w-4 text-primary mx-auto mb-1" />, value: profile.leads, label: "Leads" },
          { icon: <TrendingUp className="h-4 w-4 text-stage-deposited mx-auto mb-1" />, value: profile.deposits, label: "Deposits" },
          { icon: <Trophy className="h-4 w-4 text-stage-qualified mx-auto mb-1" />, value: `${profile.conversion_rate}%`, label: "Conv." },
          { icon: <DollarSign className="h-4 w-4 text-stage-hesitant mx-auto mb-1" />, value: `$${profile.commission_earned.toLocaleString()}`, label: "Commission" },
        ].map(({ icon, value, label }) => (
          <div key={label} className="ios-card p-2.5 text-center">
            {icon}
            <p className="text-[13px] font-bold text-foreground leading-none tabular-nums">{value}</p>
            <p className="text-[10px] text-muted-foreground mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Setup progress */}
      <div className="px-4 pt-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider">Setup Progress</p>
          <span className={cn(
            "text-[12px] font-bold tabular-nums",
            done === TOTAL ? "text-stage-deposited" : "text-muted-foreground"
          )}>
            {done}/{TOTAL} {done === TOTAL ? "— Complete!" : ""}
          </span>
        </div>
        <div className="h-2 rounded-full bg-secondary overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all duration-500", done === TOTAL ? "bg-stage-deposited" : "bg-primary")}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Checklist steps */}
      <div className="px-4 pt-3 pb-8">
        <div className="ios-card overflow-hidden">
          {STEPS.map((step) => (
            <StepRow
              key={step.kind === "bool" || step.kind === "text" ? step.key : step.idKey}
              step={step}
              profile={profile}
              onSave={handlePatch}
            />
          ))}
        </div>
      </div>

    </div>
  );
}
