import { useEffect, useState, useCallback } from "react";
import { Users, Zap, AlertTriangle, TrendingDown, Star, MessageCircle } from "lucide-react";
import { fetchMembers, reengageMember, confirmDeposit, VipMember, ActivityStatus } from "../api/members";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Status config
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<ActivityStatus, {
  label: string;
  color: string;
  bg: string;
  border: string;
  icon: React.ReactNode;
  description: string;
}> = {
  active: {
    label: "Active",
    color: "text-stage-deposited",
    bg: "bg-stage-deposited/10",
    border: "border-stage-deposited/20",
    icon: <TrendingDown className="h-3 w-3 rotate-180" />,
    description: "Activity in last 7 days",
  },
  at_risk: {
    label: "At Risk",
    color: "text-stage-hesitant",
    bg: "bg-stage-hesitant/10",
    border: "border-stage-hesitant/20",
    icon: <AlertTriangle className="h-3 w-3" />,
    description: "No activity 7–14 days",
  },
  churned: {
    label: "Churned",
    color: "text-destructive",
    bg: "bg-destructive/10",
    border: "border-destructive/20",
    icon: <TrendingDown className="h-3 w-3" />,
    description: "No activity 14+ days",
  },
  high_value: {
    label: "High Value",
    color: "text-stage-qualified",
    bg: "bg-stage-qualified/10",
    border: "border-stage-qualified/20",
    icon: <Star className="h-3 w-3" />,
    description: "VIP Member — Priority attention",
  },
};

type StatusFilter = "all" | ActivityStatus;

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "all",        label: "All" },
  { key: "high_value", label: "High Value" },
  { key: "at_risk",    label: "At Risk" },
  { key: "churned",    label: "Churned" },
  { key: "active",     label: "Active" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MembersDashboard() {
  const [members, setMembers] = useState<VipMember[]>([]);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [sentId, setSentId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [confirmedId, setConfirmedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMembers();
      setMembers(data);
    } catch (e: any) {
      setError(e?.message || "Failed to load members");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleConfirmDeposit = useCallback(async (member: VipMember) => {
    setConfirmingId(member.id);
    try {
      await confirmDeposit(member.id);
      setConfirmedId(member.id);
      load();
    } catch (e: any) {
      setError(e?.message || "Failed to confirm deposit");
    } finally {
      setConfirmingId(null);
    }
  }, [load]);

  const handleReengage = useCallback(async (member: VipMember) => {
    setSendingId(member.id);
    try {
      await reengageMember(member.id);
      setSentId(member.id);
      setTimeout(() => setSentId(null), 3000);
    } catch (e: any) {
      setError(e?.message || "Failed to send re-engagement");
    } finally {
      setSendingId(null);
    }
  }, []);

  const filtered = filter === "all"
    ? members
    : members.filter((m) => m.activity_status === filter);

  // Stats
  const counts = members.reduce((acc, m) => {
    acc[m.activity_status] = (acc[m.activity_status] || 0) + 1;
    return acc;
  }, {} as Record<ActivityStatus, number>);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Loading members...
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
    <div className="flex flex-col h-full bg-[hsl(var(--ios-grouped-bg))]">

      {/* Sticky header */}
      <div className="bg-card/80 backdrop-blur-xl sticky top-0 z-10">
        <div className="px-4 pt-2 pb-1">
          <p className="text-xs text-muted-foreground">{members.length} paid members</p>
        </div>

        {/* Filter pills */}
        <div className="px-4 pb-2 flex gap-1.5 overflow-x-auto scrollbar-hide">
          {FILTERS.map(({ key, label }) => {
            const count = key === "all" ? members.length : (counts[key as ActivityStatus] || 0);
            return (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={cn(
                  "flex items-center gap-1 px-3 py-1.5 rounded-full text-[12px] font-semibold whitespace-nowrap transition-all",
                  filter === key
                    ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                    : "bg-secondary text-muted-foreground"
                )}
              >
                {label}
                {count > 0 && (
                  <span className={cn(
                    "text-[10px] font-bold rounded-full px-1",
                    filter === key ? "text-primary-foreground/80" : "text-muted-foreground"
                  )}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* At-risk alert banner */}
      {(counts.at_risk || 0) > 0 && (
        <button
          onClick={() => setFilter("at_risk")}
          className="mx-4 mt-3 flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-stage-hesitant/10 border border-stage-hesitant/25 text-left"
        >
          <AlertTriangle className="h-4 w-4 text-stage-hesitant shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-[12px] font-semibold text-stage-hesitant">
              {counts.at_risk} member{counts.at_risk > 1 ? "s" : ""} at risk
            </p>
            <p className="text-[11px] text-muted-foreground">No activity in 7–14 days — tap to review</p>
          </div>
        </button>
      )}

      {/* Stats row */}
      <div className="px-4 py-3 grid grid-cols-4 gap-2">
        {(["high_value", "active", "at_risk", "churned"] as ActivityStatus[]).map((status) => {
          const cfg = STATUS_CONFIG[status];
          return (
            <button
              key={status}
              onClick={() => setFilter(status)}
              className={cn("ios-card p-2.5 text-center transition-all", filter === status && "ring-1 ring-primary/30")}
            >
              <p className={cn("text-lg font-bold leading-none", cfg.color)}>
                {counts[status] || 0}
              </p>
              <p className="text-[10px] text-muted-foreground mt-0.5">{cfg.label}</p>
            </button>
          );
        })}
      </div>

      {/* Member list */}
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {filtered.length === 0 ? (
          <div className="ios-card p-6 text-center">
            <p className="text-sm text-muted-foreground">No members in this category</p>
          </div>
        ) : (
          <div className="ios-card overflow-hidden divide-y divide-[hsl(var(--ios-separator))]">
            {filtered.map((member) => {
              const cfg = STATUS_CONFIG[member.activity_status];
              const isInactive = member.activity_status === "at_risk" || member.activity_status === "churned";
              const isSent = sentId === member.id;
              const isSending = sendingId === member.id;

              return (
                <div
                  key={member.id}
                  className={cn(
                    "flex items-center gap-3 px-3.5 py-3",
                    member.activity_status === "churned" && "bg-destructive/5",
                    member.activity_status === "at_risk" && "bg-stage-hesitant/5",
                  )}
                >
                  {/* Left: activity status bar */}
                  <div className={cn(
                    "w-1 self-stretch rounded-full shrink-0",
                    member.activity_status === "active" && "bg-stage-deposited",
                    member.activity_status === "at_risk" && "bg-stage-hesitant",
                    member.activity_status === "churned" && "bg-destructive",
                    member.activity_status === "high_value" && "bg-stage-qualified",
                  )} />

                  {/* Avatar */}
                  <div className="h-11 w-11 rounded-full bg-secondary flex items-center justify-center text-sm font-semibold text-foreground shrink-0">
                    {member.avatar}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-semibold text-foreground truncate">{member.name}</span>
                      {member.stage === 8 && (
                        <Star className="h-3 w-3 text-stage-qualified shrink-0" />
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className={cn("text-[11px] font-semibold", cfg.color)}>
                        {cfg.label}
                      </span>
                      {member.days_inactive !== null && (
                        <span className="text-[11px] text-muted-foreground">
                          · {member.days_inactive < 1
                            ? `${Math.round(member.days_inactive * 24)}h ago`
                            : `${Math.floor(member.days_inactive)}d ago`}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Re-engage button — only for at_risk and churned */}
                  {isInactive && (
                    <button
                      onClick={() => handleReengage(member)}
                      disabled={isSending || isSent}
                      className={cn(
                        "shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold transition-all",
                        isSent
                          ? "bg-stage-deposited/15 text-stage-deposited"
                          : "bg-primary/15 text-primary active:bg-primary/25",
                        isSending && "opacity-50"
                      )}
                    >
                      {isSent ? (
                        <>Sent ✓</>
                      ) : (
                        <>
                          <MessageCircle className="h-3 w-3" />
                          {isSending ? "…" : member.activity_status === "at_risk" ? "Check In" : "Re-engage"}
                        </>
                      )}
                    </button>
                  )}

                  {/* Confirm deposit — stage 7 only */}
                  {member.stage === 7 && confirmedId !== member.id && (
                    <button
                      onClick={() => handleConfirmDeposit(member)}
                      disabled={confirmingId === member.id}
                      className={cn(
                        "shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold transition-all",
                        "bg-stage-qualified/15 text-stage-qualified active:bg-stage-qualified/25",
                        confirmingId === member.id && "opacity-50"
                      )}
                    >
                      <Star className="h-3 w-3" />
                      {confirmingId === member.id ? "…" : "Confirm VIP"}
                    </button>
                  )}

                  {/* High value flag */}
                  {member.activity_status === "high_value" && (
                    <div className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold bg-stage-qualified/15 text-stage-qualified">
                      <Zap className="h-3 w-3" />
                      Priority
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
