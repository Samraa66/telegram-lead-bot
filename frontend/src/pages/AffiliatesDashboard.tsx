import { useEffect, useState, useCallback, useRef } from "react";
import { Trophy, Users, TrendingUp, DollarSign, Check, Plus, X, Link, ChevronDown, ChevronUp, Radio, RefreshCw, Copy } from "lucide-react";
import {
  fetchAffiliatePerformance,
  createAffiliate,
  deleteAffiliate,
  updateAffiliateLots,
  updateAffiliateChecklist,
  fetchPendingChannels,
  linkChannel,
  dismissPendingChannel,
  triggerChannelSync,
  AffiliatePerformance,
  AffiliateChecklist,
  PendingChannel,
} from "../api/affiliates";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Add Affiliate Modal
// ---------------------------------------------------------------------------

interface AddAffiliateModalProps {
  onClose: () => void;
  onCreated: (affiliate: AffiliatePerformance) => void;
}

function AddAffiliateModal({ onClose, onCreated }: AddAffiliateModalProps) {
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [commissionRate, setCommissionRate] = useState("15");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!name.trim()) { setError("Name is required"); return; }
    setLoading(true);
    setError(null);
    try {
      const affiliate = await createAffiliate({
        name: name.trim(),
        username: username.trim() || undefined,
        commission_rate: parseFloat(commissionRate) || 15,
      });
      onCreated(affiliate);
      onClose();
    } catch (e: any) {
      setError(e?.message || "Failed to create affiliate");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed inset-x-4 top-1/2 -translate-y-1/2 z-50 bg-card rounded-2xl shadow-xl p-5 max-w-sm mx-auto space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-bold text-foreground">Add Affiliate</p>
          <button onClick={onClose} className="p-1.5 text-muted-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        {error && (
          <p className="text-xs text-destructive bg-destructive/10 px-3 py-2 rounded-lg">{error}</p>
        )}

        <div className="space-y-3">
          <div>
            <label className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider">Name *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Jason Rivera"
              className="mt-1 w-full px-3 py-2 rounded-xl bg-secondary text-sm text-foreground outline-none placeholder:text-muted-foreground/50"
            />
          </div>
          <div>
            <label className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider">Telegram Handle</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="@username (optional)"
              className="mt-1 w-full px-3 py-2 rounded-xl bg-secondary text-sm text-foreground outline-none placeholder:text-muted-foreground/50"
            />
          </div>
          <div>
            <label className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider">Commission Rate (USD/lot)</label>
            <input
              type="number"
              value={commissionRate}
              onChange={(e) => setCommissionRate(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-xl bg-secondary text-sm text-foreground outline-none"
            />
          </div>
        </div>

        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"
        >
          {loading ? "Creating…" : "Create Affiliate"}
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Setup Checklist (expandable per-affiliate)
// ---------------------------------------------------------------------------

type ChecklistStep =
  | { kind: "bool"; key: keyof AffiliateChecklist; label: string }
  | { kind: "channel"; idKey: keyof AffiliateChecklist; membersKey: keyof AffiliateChecklist; label: string; target: number }
  | { kind: "text"; key: keyof AffiliateChecklist; label: string; placeholder: string };

const CHECKLIST_STEPS: ChecklistStep[] = [
  { kind: "bool",    key: "esim_done",          label: "Secondary phone / eSIM" },
  { kind: "channel", idKey: "free_channel_id",  membersKey: "free_channel_members",    label: "Free channel",    target: 2000 },
  { kind: "bool",    key: "bot_setup_done",      label: "Bot configured (welcome + auto-approve)" },
  { kind: "channel", idKey: "vip_channel_id",   membersKey: "vip_channel_members",     label: "VIP channel",     target: 60 },
  { kind: "channel", idKey: "tutorial_channel_id", membersKey: "tutorial_channel_members", label: "Tutorial channel", target: 50 },
  { kind: "bool",    key: "sales_scripts_done",  label: "Sales scripts in quick replies" },
  { kind: "text",    key: "ib_profile_id",       label: "PU Prime IB profile ID", placeholder: "e.g. IB-12345" },
  { kind: "bool",    key: "pixel_setup_done",    label: "Pixel setup" },
  { kind: "bool",    key: "ads_live",            label: "Ads running" },
];

function checklistProgress(aff: AffiliateChecklist): number {
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

const CHECKLIST_TOTAL = 9;

interface SetupChecklistProps {
  affiliate: AffiliatePerformance;
  onUpdated: (patch: Partial<AffiliateChecklist>) => void;
}

function SetupChecklist({ affiliate, onUpdated }: SetupChecklistProps) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const done = checklistProgress(affiliate);
  const pct = Math.round((done / CHECKLIST_TOTAL) * 100);

  const save = async (patch: Partial<AffiliateChecklist>) => {
    onUpdated(patch);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        await updateAffiliateChecklist(affiliate.id, patch);
      } catch { /* silently retry on next interaction */ }
    }, 600);
  };

  const toggleBool = (key: keyof AffiliateChecklist) => {
    const patch = { [key]: !affiliate[key] } as Partial<AffiliateChecklist>;
    setSaving(key);
    save(patch).finally(() => setSaving(null));
  };

  const setTextValue = (key: keyof AffiliateChecklist, val: string) => {
    save({ [key]: val || null } as Partial<AffiliateChecklist>);
  };

  const setMembersValue = (key: keyof AffiliateChecklist, val: string) => {
    save({ [key]: parseInt(val) || 0 } as Partial<AffiliateChecklist>);
  };

  return (
    <div className="border-t border-[hsl(var(--ios-separator))] pt-2.5 mt-0.5">
      {/* Header row — always visible */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 group"
      >
        <div className="flex-1">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] text-muted-foreground font-semibold">Setup</span>
            <span className={cn(
              "text-[11px] font-bold tabular-nums",
              done === CHECKLIST_TOTAL ? "text-stage-deposited" : "text-muted-foreground"
            )}>
              {done}/{CHECKLIST_TOTAL}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-300",
                done === CHECKLIST_TOTAL ? "bg-stage-deposited" : "bg-primary"
              )}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        <span className="text-muted-foreground shrink-0 ml-1">
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </span>
      </button>

      {/* Expanded steps */}
      {open && (
        <div className="mt-3 space-y-2.5">
          {CHECKLIST_STEPS.map((step) => {
            if (step.kind === "bool") {
              const checked = Boolean(affiliate[step.key]);
              return (
                <button
                  key={step.key}
                  onClick={() => toggleBool(step.key)}
                  disabled={saving === step.key}
                  className="w-full flex items-center gap-2.5 text-left"
                >
                  <span className={cn(
                    "h-5 w-5 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors",
                    checked
                      ? "bg-stage-deposited border-stage-deposited"
                      : "border-muted-foreground/30"
                  )}>
                    {checked && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
                  </span>
                  <span className={cn(
                    "text-[12px]",
                    checked ? "text-muted-foreground line-through" : "text-foreground"
                  )}>
                    {step.label}
                  </span>
                </button>
              );
            }

            if (step.kind === "channel") {
              const channelId = (affiliate[step.idKey] as string | null) || "";
              const members = (affiliate[step.membersKey] as number) || 0;
              const isDone = Boolean(channelId);
              return (
                <div key={step.idKey} className="space-y-1.5">
                  <div className="flex items-center gap-2.5">
                    <span className={cn(
                      "h-5 w-5 rounded-full border-2 flex items-center justify-center shrink-0",
                      isDone ? "bg-stage-deposited border-stage-deposited" : "border-muted-foreground/30"
                    )}>
                      {isDone && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
                    </span>
                    <span className={cn(
                      "text-[12px] font-medium",
                      isDone ? "text-muted-foreground" : "text-foreground"
                    )}>
                      {step.label}
                    </span>
                    <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">
                      {members.toLocaleString()} / {step.target.toLocaleString()} members
                    </span>
                  </div>
                  <div className="pl-7 flex gap-2">
                    <input
                      defaultValue={channelId}
                      onBlur={(e) => setTextValue(step.idKey, e.target.value)}
                      placeholder="Channel ID (e.g. -1001234567)"
                      className="flex-1 px-2.5 py-1.5 rounded-lg bg-secondary text-[11px] text-foreground outline-none placeholder:text-muted-foreground/40"
                    />
                    <input
                      type="number"
                      defaultValue={members || ""}
                      onBlur={(e) => setMembersValue(step.membersKey, e.target.value)}
                      placeholder="Members"
                      className="w-20 px-2.5 py-1.5 rounded-lg bg-secondary text-[11px] text-foreground outline-none placeholder:text-muted-foreground/40"
                    />
                  </div>
                </div>
              );
            }

            // text
            const val = (affiliate[step.key] as string | null) || "";
            const isDone = Boolean(val);
            return (
              <div key={step.key} className="space-y-1.5">
                <div className="flex items-center gap-2.5">
                  <span className={cn(
                    "h-5 w-5 rounded-full border-2 flex items-center justify-center shrink-0",
                    isDone ? "bg-stage-deposited border-stage-deposited" : "border-muted-foreground/30"
                  )}>
                    {isDone && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
                  </span>
                  <span className={cn(
                    "text-[12px] font-medium",
                    isDone ? "text-muted-foreground" : "text-foreground"
                  )}>
                    {step.label}
                  </span>
                </div>
                <div className="pl-7">
                  <input
                    defaultValue={val}
                    onBlur={(e) => setTextValue(step.key, e.target.value)}
                    placeholder={step.placeholder}
                    className="w-full px-2.5 py-1.5 rounded-lg bg-secondary text-[11px] text-foreground outline-none placeholder:text-muted-foreground/40"
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lots Editor (inline)
// ---------------------------------------------------------------------------

interface LotsEditorProps {
  affiliate: AffiliatePerformance;
  onSaved: (lots: number) => void;
}

function LotsEditor({ affiliate, onSaved }: LotsEditorProps) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(affiliate.lots_traded));
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateAffiliateLots(affiliate.id, parseFloat(value) || 0);
      onSaved(parseFloat(value) || 0);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="text-[12px] text-muted-foreground hover:text-foreground transition-colors tabular-nums"
      >
        {affiliate.lots_traded} lots
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <input
        type="number"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="w-16 px-2 py-0.5 rounded-lg bg-secondary text-[12px] text-foreground outline-none"
        autoFocus
      />
      <button
        onClick={handleSave}
        disabled={saving}
        className="text-[11px] font-semibold text-primary disabled:opacity-50"
      >
        {saving ? "…" : "Save"}
      </button>
      <button onClick={() => setEditing(false)} className="text-[11px] text-muted-foreground">
        Cancel
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Credentials Modal (shown once after affiliate creation)
// ---------------------------------------------------------------------------

interface CredentialsModalProps {
  name: string;
  username: string;
  password: string;
  onClose: () => void;
}

function CredentialsModal({ name, username, password, onClose }: CredentialsModalProps) {
  const [copiedAll, setCopiedAll] = useState(false);
  const dashboardUrl = window.location.origin + "/portal";
  const fullText = `Dashboard: ${dashboardUrl}\nUsername: ${username}\nPassword: ${password}`;

  const copyAll = () => {
    navigator.clipboard.writeText(fullText).catch(() => {});
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2000);
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40" />
      <div className="fixed inset-x-4 top-1/2 -translate-y-1/2 z-50 bg-card rounded-2xl shadow-xl p-5 max-w-sm mx-auto space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-bold text-foreground">Login Created — {name}</p>
          <button onClick={onClose} className="p-1.5 text-muted-foreground"><X className="h-4 w-4" /></button>
        </div>

        <p className="text-[12px] text-muted-foreground">
          Share these credentials with the affiliate. The password is only shown once.
        </p>

        <div className="bg-secondary rounded-xl p-3.5 space-y-2 font-mono text-[12px]">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Dashboard</span>
            <span className="text-foreground truncate max-w-[150px]">{dashboardUrl}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Username</span>
            <span className="text-foreground">{username}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Password</span>
            <span className="text-primary font-bold">{password}</span>
          </div>
        </div>

        <button
          onClick={copyAll}
          className={cn(
            "w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-colors",
            copiedAll
              ? "bg-stage-deposited/15 text-stage-deposited"
              : "bg-primary text-primary-foreground"
          )}
        >
          {copiedAll ? <><Check className="h-4 w-4" /> Copied!</> : <><Copy className="h-4 w-4" /> Copy All to Share</>}
        </button>

        <button onClick={onClose} className="w-full text-center text-[12px] text-muted-foreground py-1">
          I've saved the credentials
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Pending Channel Row
// ---------------------------------------------------------------------------

interface PendingChannelRowProps {
  channel: PendingChannel;
  affiliates: AffiliatePerformance[];
  onLinked: (chatId: string, affiliateId: number, type: "free" | "vip" | "tutorial") => void;
  onDismissed: (id: number) => void;
}

function PendingChannelRow({ channel, affiliates, onLinked, onDismissed }: PendingChannelRowProps) {
  const [selectedAffiliate, setSelectedAffiliate] = useState("");
  const [selectedType, setSelectedType] = useState<"free" | "vip" | "tutorial">("free");
  const [saving, setSaving] = useState(false);

  const handleLink = async () => {
    if (!selectedAffiliate) return;
    setSaving(true);
    try {
      await linkChannel(parseInt(selectedAffiliate), channel.chat_id, selectedType);
      onLinked(channel.chat_id, parseInt(selectedAffiliate), selectedType);
    } finally {
      setSaving(false);
    }
  };

  const handleDismiss = async () => {
    await dismissPendingChannel(channel.id);
    onDismissed(channel.id);
  };

  return (
    <div className="px-3.5 py-3 space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[13px] font-semibold text-foreground">{channel.title || "Unnamed channel"}</p>
          <p className="text-[11px] text-muted-foreground font-mono">{channel.chat_id}</p>
        </div>
        <button onClick={handleDismiss} className="p-1 text-muted-foreground/50 hover:text-muted-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex items-center gap-2">
        <select
          value={selectedAffiliate}
          onChange={(e) => setSelectedAffiliate(e.target.value)}
          className="flex-1 px-2.5 py-1.5 rounded-lg bg-secondary text-[12px] text-foreground outline-none"
        >
          <option value="">Select affiliate…</option>
          {affiliates.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <select
          value={selectedType}
          onChange={(e) => setSelectedType(e.target.value as "free" | "vip" | "tutorial")}
          className="w-24 px-2.5 py-1.5 rounded-lg bg-secondary text-[12px] text-foreground outline-none"
        >
          <option value="free">Free</option>
          <option value="vip">VIP</option>
          <option value="tutorial">Tutorial</option>
        </select>
        <button
          onClick={handleLink}
          disabled={!selectedAffiliate || saving}
          className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-[12px] font-semibold disabled:opacity-40"
        >
          {saving ? "…" : "Link"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard
// ---------------------------------------------------------------------------

export default function AffiliatesDashboard() {
  const [affiliates, setAffiliates] = useState<AffiliatePerformance[]>([]);
  const [pending, setPending] = useState<PendingChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [copiedTag, setCopiedTag] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [newCredentials, setNewCredentials] = useState<{ username: string; password: string; name: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, pendingData] = await Promise.all([
        fetchAffiliatePerformance(),
        fetchPendingChannels(),
      ]);
      setAffiliates(data);
      setPending(pendingData);
    } catch (e: any) {
      setError(e?.message || "Failed to load affiliates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSyncChannels = async () => {
    setSyncing(true);
    try {
      await triggerChannelSync();
      // Reload after a short delay to pick up updated counts
      setTimeout(() => load(), 3000);
    } finally {
      setSyncing(false);
    }
  };

  const handleCopy = (link: string, tag: string) => {
    navigator.clipboard.writeText(link).catch(() => {});
    setCopiedTag(tag);
    setTimeout(() => setCopiedTag(null), 2000);
  };

  const handleLotsUpdated = (affiliateId: number, lots: number) => {
    setAffiliates((prev) =>
      prev.map((a) =>
        a.id === affiliateId
          ? { ...a, lots_traded: lots, commission_earned: Math.round(lots * a.commission_rate * 100) / 100 }
          : a
      )
    );
  };

  const handleChecklistUpdated = (affiliateId: number, patch: Partial<AffiliateChecklist>) => {
    setAffiliates((prev) =>
      prev.map((a) => (a.id === affiliateId ? { ...a, ...patch } : a))
    );
  };

  const handleDelete = async (affiliateId: number, name: string) => {
    if (!window.confirm(`Remove ${name}? This cannot be undone.`)) return;
    try {
      await deleteAffiliate(affiliateId);
      setAffiliates((prev) => prev.filter((a) => a.id !== affiliateId));
    } catch {
      alert("Failed to delete affiliate.");
    }
  };

  // Summary stats
  const totalLeads = affiliates.reduce((s, a) => s + a.leads, 0);
  const totalDeposits = affiliates.reduce((s, a) => s + a.deposits, 0);
  const totalCommission = affiliates.reduce((s, a) => s + a.commission_earned, 0);
  const overallConversion = totalLeads > 0 ? Math.round((totalDeposits / totalLeads) * 1000) / 10 : 0;

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Loading affiliates...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-destructive text-sm px-4 text-center">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[hsl(var(--ios-grouped-bg))] overflow-y-auto">

      {/* Header */}
      <div className="bg-card/80 backdrop-blur-xl sticky top-0 z-10 px-4 pt-2 pb-3 flex items-center justify-between border-b border-[hsl(var(--ios-separator))]">
        <p className="text-xs text-muted-foreground">{affiliates.length} affiliate{affiliates.length !== 1 ? "s" : ""}</p>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSyncChannels}
            disabled={syncing}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-secondary text-muted-foreground text-[12px] font-semibold disabled:opacity-50"
            title="Sync channel member counts"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", syncing && "animate-spin")} />
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-primary/15 text-primary text-[12px] font-semibold"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Affiliate
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="px-4 py-3 grid grid-cols-4 gap-2">
        {[
          { icon: <Users className="h-4 w-4 text-primary mx-auto mb-1" />, value: totalLeads,            label: "Leads" },
          { icon: <TrendingUp className="h-4 w-4 text-stage-deposited mx-auto mb-1" />, value: totalDeposits, label: "Deposits" },
          { icon: <Trophy className="h-4 w-4 text-stage-qualified mx-auto mb-1" />, value: `${overallConversion}%`, label: "Conv." },
          { icon: <DollarSign className="h-4 w-4 text-stage-hesitant mx-auto mb-1" />, value: `$${totalCommission.toLocaleString()}`, label: "Commission" },
        ].map(({ icon, value, label }) => (
          <div key={label} className="ios-card p-2.5 text-center">
            {icon}
            <p className="text-[13px] font-bold text-foreground leading-none tabular-nums">{value}</p>
            <p className="text-[10px] text-muted-foreground mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Pending Channels */}
      {pending.length > 0 && (
        <div className="px-4 pb-2 space-y-2">
          <p className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider px-0.5 flex items-center gap-1.5">
            <Radio className="h-3 w-3 text-primary" />
            Unlinked Channels ({pending.length})
          </p>
          <div className="ios-card overflow-hidden divide-y divide-[hsl(var(--ios-separator))]">
            {pending.map((ch) => (
              <PendingChannelRow
                key={ch.id}
                channel={ch}
                affiliates={affiliates}
                onLinked={(chatId, affiliateId, type) => {
                  setPending((prev) => prev.filter((c) => c.chat_id !== chatId));
                  setAffiliates((prev) => prev.map((a) =>
                    a.id === affiliateId
                      ? { ...a, [`${type}_channel_id`]: chatId }
                      : a
                  ));
                }}
                onDismissed={(id) => setPending((prev) => prev.filter((c) => c.id !== id))}
              />
            ))}
          </div>
        </div>
      )}

      {/* Leaderboard */}
      <div className="px-4 pb-4 space-y-2">
        <p className="text-[11px] text-muted-foreground font-semibold uppercase tracking-wider px-0.5">
          Leaderboard
        </p>

        {affiliates.length === 0 ? (
          <div className="ios-card p-6 text-center">
            <p className="text-sm text-muted-foreground">No affiliates yet — add the first one</p>
          </div>
        ) : (
          <div className="ios-card overflow-hidden divide-y divide-[hsl(var(--ios-separator))]">
            {affiliates.map((aff, idx) => (
              <div key={aff.id} className="px-3.5 py-3.5 space-y-2.5">

                {/* Row 1: rank + name + conversion badge */}
                <div className="flex items-center gap-3">
                  <span className={cn(
                    "h-7 w-7 rounded-full flex items-center justify-center text-[12px] font-bold shrink-0",
                    idx === 0 && "bg-stage-qualified/20 text-stage-qualified",
                    idx === 1 && "bg-muted-foreground/15 text-muted-foreground",
                    idx === 2 && "bg-stage-hesitant/15 text-stage-hesitant",
                    idx > 2 && "bg-secondary text-muted-foreground",
                  )}>
                    {idx === 0 ? <Trophy className="h-3.5 w-3.5" /> : `#${idx + 1}`}
                  </span>

                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-semibold text-foreground">{aff.name}</p>
                    {aff.username && (
                      <p className="text-[11px] text-muted-foreground">{aff.username}</p>
                    )}
                  </div>

                  <span className={cn(
                    "shrink-0 text-[11px] font-bold px-2 py-0.5 rounded-full",
                    aff.conversion_rate >= 25 ? "bg-stage-deposited/15 text-stage-deposited" :
                    aff.conversion_rate >= 15 ? "bg-primary/15 text-primary" :
                    "bg-secondary text-muted-foreground"
                  )}>
                    {aff.conversion_rate}% conv.
                  </span>
                </div>

                {/* Row 2: stats */}
                <div className="grid grid-cols-3 gap-2">
                  <div className="bg-secondary rounded-xl p-2 text-center">
                    <p className="text-[13px] font-bold text-foreground tabular-nums">{aff.leads}</p>
                    <p className="text-[10px] text-muted-foreground">Leads</p>
                  </div>
                  <div className="bg-secondary rounded-xl p-2 text-center">
                    <p className="text-[13px] font-bold text-stage-deposited tabular-nums">{aff.deposits}</p>
                    <p className="text-[10px] text-muted-foreground">Deposits</p>
                  </div>
                  <div className="bg-secondary rounded-xl p-2 text-center">
                    <p className="text-[13px] font-bold text-stage-qualified tabular-nums">${aff.commission_earned.toLocaleString()}</p>
                    <p className="text-[10px] text-muted-foreground">Commission</p>
                  </div>
                </div>

                {/* Row 3: lots + referral link */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-muted-foreground">Lots traded:</span>
                    <LotsEditor
                      affiliate={aff}
                      onSaved={(lots) => handleLotsUpdated(aff.id, lots)}
                    />
                    <span className="text-[11px] text-muted-foreground">
                      · ${aff.commission_rate}/lot
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {aff.referral_link && (
                      <button
                        onClick={() => handleCopy(aff.referral_link!, aff.referral_tag)}
                        className={cn(
                          "flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold transition-all",
                          copiedTag === aff.referral_tag
                            ? "bg-stage-deposited/15 text-stage-deposited"
                            : "bg-secondary text-muted-foreground active:bg-accent"
                        )}
                      >
                        {copiedTag === aff.referral_tag ? (
                          <><Check className="h-3 w-3" /> Copied</>
                        ) : (
                          <><Link className="h-3 w-3" /> Copy Link</>
                        )}
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(aff.id, aff.name)}
                      className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold text-destructive bg-destructive/10 active:bg-destructive/20 transition-all"
                    >
                      <X className="h-3 w-3" /> Remove
                    </button>
                  </div>
                </div>

                {/* Row 4: onboarding checklist */}
                <SetupChecklist
                  affiliate={aff}
                  onUpdated={(patch) => handleChecklistUpdated(aff.id, patch)}
                />

              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <AddAffiliateModal
          onClose={() => setShowAddModal(false)}
          onCreated={(affiliate) => {
            setAffiliates((prev) => [affiliate, ...prev]);
            if (affiliate.login_username && affiliate.login_password) {
              setNewCredentials({ username: affiliate.login_username, password: affiliate.login_password, name: affiliate.name });
            }
          }}
        />
      )}

      {/* Credentials reveal modal */}
      {newCredentials && (
        <CredentialsModal
          name={newCredentials.name}
          username={newCredentials.username}
          password={newCredentials.password}
          onClose={() => setNewCredentials(null)}
        />
      )}
    </div>
  );
}
