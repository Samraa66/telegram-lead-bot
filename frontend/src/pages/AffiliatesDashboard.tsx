import { useEffect, useState, useCallback } from "react";
import { Trophy, Users, TrendingUp, DollarSign, Copy, Check, Plus, X, Link } from "lucide-react";
import {
  fetchAffiliatePerformance,
  createAffiliate,
  updateAffiliateLots,
  AffiliatePerformance,
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
// Main Dashboard
// ---------------------------------------------------------------------------

export default function AffiliatesDashboard() {
  const [affiliates, setAffiliates] = useState<AffiliatePerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [copiedTag, setCopiedTag] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAffiliatePerformance();
      setAffiliates(data);
    } catch (e: any) {
      setError(e?.message || "Failed to load affiliates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

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
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-primary/15 text-primary text-[12px] font-semibold"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Affiliate
        </button>
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
                </div>

              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <AddAffiliateModal
          onClose={() => setShowAddModal(false)}
          onCreated={(affiliate) => setAffiliates((prev) => [affiliate, ...prev])}
        />
      )}
    </div>
  );
}
