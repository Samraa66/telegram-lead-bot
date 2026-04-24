import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Copy, Check, Users, TrendingUp, DollarSign, Trophy,
  ChevronDown, ChevronUp, ExternalLink,
} from "lucide-react";
import { fetchMyProfile, updateMyChecklist, AffiliateProfile } from "../api/affiliateMe";
import { AffiliateChecklist } from "../api/affiliates";
import { cn } from "../lib/utils";
import WorkspaceHealthCard from "../components/WorkspaceHealthCard";

// ---------------------------------------------------------------------------
// Checklist definition — grouped into the 4-stage mental model
//   1. Core connections (auto-derived from workspace state)
//   2. Build your audience
//   3. Sales process
//   4. Turn on traffic
// ---------------------------------------------------------------------------

type ChecklistStep =
  | { kind: "bool"; key: keyof AffiliateChecklist; label: string; guide: string }
  | { kind: "channel"; idKey: keyof AffiliateChecklist; membersKey: keyof AffiliateChecklist; label: string; target: number; guide: string }
  | { kind: "text"; key: keyof AffiliateChecklist; label: string; placeholder: string; guide: string }
  // "derived" rows reflect real workspace state — not toggleable. Their value is
  // read from profile[key] (a server-derived boolean) and the CTA links the user
  // to the correct place to configure it.
  | { kind: "derived"; key: keyof AffiliateChecklist; label: string; guide: string; ctaLabel: string; ctaPath: string };

type ChecklistGroup = { title: string; eyebrow: string; steps: ChecklistStep[] };

const GROUPS: ChecklistGroup[] = [
  {
    eyebrow: "01",
    title: "Core connections",
    steps: [
      {
        kind: "derived", key: "has_bot_token", label: "Acquisition Bot connected",
        guide: "The Telegram bot that captures leads clicking your ads. Configured in onboarding — go back there or to Settings → Telegram to change it.",
        ctaLabel: "Open Settings → Acquisition Bot", ctaPath: "/settings",
      },
      {
        kind: "derived", key: "has_conversion_desk", label: "Conversion Desk connected",
        guide: "Your personal Telegram — the human that replies to leads and closes them. If this shows red, reconnect from Settings → Telegram.",
        ctaLabel: "Open Settings → Conversion Desk", ctaPath: "/settings",
      },
      {
        kind: "channel", idKey: "vip_channel_id", membersKey: "vip_channel_members",
        label: "Signals channel linked", target: 60,
        guide: "Your private paid channel. Once the ID is linked, trade signals forward here automatically — no ongoing work needed.",
      },
    ],
  },
  {
    eyebrow: "02",
    title: "Build your audience",
    steps: [
      {
        kind: "bool", key: "esim_done", label: "Secondary phone / eSIM",
        guide: "Get a second phone number or eSIM so your Conversion Desk is separate from your personal Telegram.",
      },
      {
        kind: "channel", idKey: "free_channel_id", membersKey: "free_channel_members",
        label: "Free channel (public)", target: 2000,
        guide: "Public Telegram channel — the top of your funnel. Post daily: morning updates, member profit screenshots, lifestyle content. Every post should drive people toward your Acquisition Bot.",
      },
      {
        kind: "bool", key: "bot_setup_done", label: "Acquisition Bot pinned in free channel",
        guide: "Pin a CTA post in your free channel that links to your Acquisition Bot. Requires Telegram Business (~€8/mo):\n1. Create a personal chat link in Telegram Business\n2. Add your bot + @ChannelHelperBot as admins in your free channel\n3. @ChannelHelperBot → Menu → Create Post → add button 'Click here' linking to your chat link\n4. Pin the post at the top",
      },
      {
        kind: "channel", idKey: "tutorial_channel_id", membersKey: "tutorial_channel_members",
        label: "Tutorial channel (public)", target: 50,
        guide: "Mid-funnel: a public channel with beginner trading lessons. Disable content saving. Copy our tutorial lessons (we'll give you access). End each lesson with a link to request access to your Signals channel.",
      },
    ],
  },
  {
    eyebrow: "03",
    title: "Sales process",
    steps: [
      {
        kind: "bool", key: "sales_scripts_done", label: "Sales scripts loaded",
        guide: "Load the sales scripts into your Conversion Desk's quick replies so you can respond to leads fast.",
      },
      {
        kind: "text", key: "ib_profile_id", label: "PU Prime IB Profile ID", placeholder: "e.g. IB-12345",
        guide: "Create your Introducing Broker account on PU Prime and paste your IB ID here. This is how your commissions are tracked.",
      },
    ],
  },
  {
    eyebrow: "04",
    title: "Turn on traffic",
    steps: [
      {
        kind: "bool", key: "pixel_setup_done", label: "Meta Pixel installed",
        guide: "Install your Meta Pixel on the landing page so your ad conversions are tracked.",
      },
      {
        kind: "bool", key: "ads_live", label: "Ads running",
        guide: "Your funnel: Ads → Free channel → Acquisition Bot → Conversion Desk → Tutorial channel → PU Prime deposit → Signals channel.",
      },
    ],
  },
];

const ALL_STEPS: ChecklistStep[] = GROUPS.flatMap(g => g.steps);
const TOTAL = ALL_STEPS.length;

function stepIsDone(step: ChecklistStep, aff: AffiliateChecklist): boolean {
  if (step.kind === "bool" || step.kind === "derived") return Boolean(aff[step.key]);
  if (step.kind === "channel") return Boolean(aff[step.idKey]);
  return Boolean(aff[step.key]);
}

function progress(aff: AffiliateChecklist): number {
  return ALL_STEPS.reduce((n, s) => n + (stepIsDone(s, aff) ? 1 : 0), 0);
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
        "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold transition-colors",
        copied ? "bg-success/15 text-success" : "bg-secondary text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
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

  const navigate = useNavigate();
  const isDone = stepIsDone(step, profile);

  return (
    <div className="border-b border-border last:border-0">
      {/* Step header */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-secondary/30 transition-colors"
      >
        <span className={cn(
          "h-5 w-5 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors",
          isDone ? "bg-success border-success" : "border-muted-foreground/30"
        )}>
          {isDone && <Check className="h-2.5 w-2.5 text-success-foreground" strokeWidth={3} />}
        </span>
        <span className={cn(
          "flex-1 text-sm font-medium",
          isDone ? "text-muted-foreground line-through" : "text-foreground"
        )}>
          {step.label}
        </span>
        {step.kind === "channel" && (
          <span className="text-xs text-muted-foreground tabular-nums shrink-0">
            {(profile[step.membersKey] as number) || 0}/{step.target.toLocaleString()}
          </span>
        )}
        <span className="text-muted-foreground shrink-0">
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </span>
      </button>

      {/* Expanded */}
      {open && (
        <div className="px-4 pb-4 pt-1 space-y-3">
          <p className="text-xs text-muted-foreground whitespace-pre-line leading-relaxed">
            {step.guide}
          </p>

          {step.kind === "bool" && (
            <button
              onClick={() => debouncedSave({ [step.key]: !profile[step.key] } as Partial<AffiliateChecklist>)}
              className={cn(
                "px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-colors",
                isDone
                  ? "bg-success/15 text-success hover:bg-success/20"
                  : "bg-primary/15 text-primary hover:bg-primary/20"
              )}
            >
              {isDone ? "Mark as not done" : "Mark as done"}
            </button>
          )}

          {step.kind === "channel" && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <label className="eyebrow">Channel ID</label>
                <input
                  defaultValue={(profile[step.idKey] as string | null) || ""}
                  onBlur={(e) => debouncedSave({ [step.idKey]: e.target.value || null } as Partial<AffiliateChecklist>)}
                  placeholder="-1001234567890"
                  className="w-full h-9 px-3 rounded-lg bg-secondary/60 border border-border text-xs text-foreground outline-none placeholder:text-muted-foreground/50 font-mono focus:border-primary focus:ring-2 focus:ring-primary/20 transition-colors"
                />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="eyebrow">Members (auto-synced)</label>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {(profile[step.membersKey] as number || 0).toLocaleString()} / {step.target.toLocaleString()}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, ((profile[step.membersKey] as number || 0) / step.target) * 100)}%` }}
                  />
                </div>
              </div>
            </div>
          )}

          {step.kind === "derived" && (
            <button
              onClick={() => navigate(step.ctaPath)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-primary/15 text-primary hover:bg-primary/20 transition-colors"
            >
              <ExternalLink className="h-3 w-3" />
              {step.ctaLabel}
            </button>
          )}

          {step.kind === "text" && (
            <input
              defaultValue={(profile[step.key] as string | null) || ""}
              onBlur={(e) => debouncedSave({ [step.key]: e.target.value || null } as Partial<AffiliateChecklist>)}
              placeholder={step.placeholder}
              className="w-full h-9 px-3 rounded-lg bg-secondary/60 border border-border text-xs text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-primary focus:ring-2 focus:ring-primary/20 transition-colors"
            />
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
    <div className="space-y-6">
      <WorkspaceHealthCard />

      {/* Referral link */}
      <div className="surface-card p-5 space-y-2.5">
        <p className="eyebrow">Your referral link</p>
        {profile.referral_link ? (
          <div className="flex items-center gap-2">
            <p className="flex-1 text-xs text-foreground font-mono truncate">{profile.referral_link}</p>
            <CopyButton text={profile.referral_link} label="Copy" />
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Referral tag: <span className="font-mono text-foreground">{profile.referral_tag}</span></p>
        )}
        <p className="text-xs text-muted-foreground">Share this everywhere. Every lead who clicks it is attributed to you automatically.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { icon: <Users className="h-4 w-4 text-primary" />, value: profile.leads, label: "Leads" },
          { icon: <TrendingUp className="h-4 w-4 text-success" />, value: profile.deposits, label: "Deposits" },
          { icon: <Trophy className="h-4 w-4 text-stage-qualified" />, value: `${profile.conversion_rate}%`, label: "Conversion" },
          { icon: <DollarSign className="h-4 w-4 text-warning" />, value: `$${profile.commission_earned.toLocaleString()}`, label: "Commission" },
        ].map(({ icon, value, label }) => (
          <div key={label} className="surface-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-muted-foreground font-medium">{label}</span>
              <div className="w-7 h-7 rounded-md bg-secondary/80 flex items-center justify-center">{icon}</div>
            </div>
            <p className="text-xl font-semibold text-foreground tabular-nums tracking-tight">{value}</p>
          </div>
        ))}
      </div>

      {/* Setup progress */}
      <div className="surface-card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <p className="eyebrow">Setup progress</p>
          <span className={cn(
            "text-xs font-semibold tabular-nums",
            done === TOTAL ? "text-success" : "text-muted-foreground"
          )}>
            {done}/{TOTAL} {done === TOTAL && "— complete"}
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all duration-500", done === TOTAL ? "bg-success" : "bg-primary")}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Checklist — grouped by pipeline stage */}
      <div className="space-y-5">
        {GROUPS.map((group) => {
          const groupDone = group.steps.filter((s) => stepIsDone(s, profile)).length;
          return (
            <div key={group.title}>
              <div className="flex items-center justify-between mb-2 px-1">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono text-muted-foreground/60">{group.eyebrow}</span>
                  <h3 className="text-sm font-semibold text-foreground tracking-tight">{group.title}</h3>
                </div>
                <span className={cn(
                  "text-[11px] font-medium tabular-nums",
                  groupDone === group.steps.length ? "text-success" : "text-muted-foreground"
                )}>
                  {groupDone}/{group.steps.length}
                </span>
              </div>
              <div className="surface-card overflow-hidden">
                {group.steps.map((step: ChecklistStep) => (
                  <StepRow
                    key={step.kind === "channel" ? step.idKey : step.key}
                    step={step}
                    profile={profile}
                    onSave={handlePatch}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
