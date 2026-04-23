import {
  Search,
  Users,
  Clock,
  TrendingUp,
  MessageCircle,
  ArrowUpDown,
  AlertTriangle,
} from "lucide-react";
import { Input } from "../ui/input";
import { useState } from "react";
import {
  Lead,
  Stage,
  STAGES,
  STAGE_COLORS,
  STAGE_TEXT_COLORS,
  formatTimeInStage,
  classificationLabel,
  classificationColor,
} from "../../data/crmData";
import { cn } from "../../lib/utils";

interface LeadListProps {
  leads: Lead[];
  selectedLeadId: string | null;
  onSelectLead: (id: string) => void;
}

function getUrgencyLevel(
  stageEnteredAt: string,
): "critical" | "high" | "normal" {
  const now = new Date();
  const hrs = (now.getTime() - new Date(stageEnteredAt).getTime()) / 3600000;
  if (hrs >= 48) return "critical";
  if (hrs >= 12) return "high";
  return "normal";
}

type ClassificationFilter =
  | "all"
  | "new_lead"
  | "warm_lead"
  | "affiliate"
  | "noise"
  | "escalated";
type StageFilter = "all" | Stage;
type SortMode = "waiting" | "active" | "newest";

const CLASSIFICATION_FILTERS: { key: ClassificationFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "escalated", label: "Escalated" },
  { key: "new_lead", label: "New" },
  { key: "warm_lead", label: "Warm" },
  { key: "affiliate", label: "Affiliate" },
  { key: "noise", label: "Noise" },
];

const SORT_MODES: { key: SortMode; label: string }[] = [
  { key: "waiting", label: "Waiting longest" },
  { key: "active", label: "Recently active" },
  { key: "newest", label: "Newest first" },
];

export function LeadList({
  leads,
  selectedLeadId,
  onSelectLead,
}: LeadListProps) {
  const [search, setSearch] = useState("");
  const [classFilter, setClassFilter] = useState<ClassificationFilter>("all");
  const [stageFilter, setStageFilter] = useState<StageFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("waiting");
  const [stageRowOpen, setStageRowOpen] = useState(false);

  function cycleSortMode() {
    setSortMode((prev) => {
      const idx = SORT_MODES.findIndex((s) => s.key === prev);
      return SORT_MODES[(idx + 1) % SORT_MODES.length].key;
    });
  }

  const filtered = leads
    .filter((l) => {
      if (classFilter === "escalated") {
        if (!l.escalated) return false;
      } else {
        if (classFilter === "all" && l.classification === "noise") return false;
        if (classFilter !== "all" && l.classification !== classFilter)
          return false;
      }
      if (stageFilter !== "all" && l.stage !== stageFilter) return false;
      if (
        search &&
        !l.name.toLowerCase().includes(search.toLowerCase()) &&
        !l.username.toLowerCase().includes(search.toLowerCase())
      )
        return false;
      return true;
    })
    .sort((a, b) => {
      if (sortMode === "waiting") {
        return (
          new Date(a.stageEnteredAt).getTime() -
          new Date(b.stageEnteredAt).getTime()
        );
      }
      if (sortMode === "active") {
        return (
          new Date(b.lastMessageAt).getTime() -
          new Date(a.lastMessageAt).getTime()
        );
      }
      // newest: highest id first (Telegram IDs are monotonically increasing)
      return Number(b.id) - Number(a.id);
    });

  // Stats
  const totalLeads = leads.length;
  const unreadCount = leads.filter((l) => l.unread > 0).length;
  const urgentCount = leads.filter(
    (l) => getUrgencyLevel(l.stageEnteredAt) !== "normal",
  ).length;
  const depositedCount = leads.filter(
    (l) =>
      l.stage === "Deposited" ||
      l.stage === "VIP Member" ||
      l.classification === "vip",
  ).length;

  return (
    <div className="flex flex-col h-full bg-[hsl(var(--ios-grouped-bg))]">
      {/* Sticky search + filter header */}
      <div className="bg-card/80 backdrop-blur-xl sticky top-0 z-10">
        <div className="px-4 pt-2 pb-1 flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {totalLeads} total
            {unreadCount > 0 && (
              <> · <span className="text-primary font-medium">{unreadCount} unread</span></>
            )}
            {urgentCount > 0 && (
              <> · <span className="text-destructive font-medium">{urgentCount} urgent</span></>
            )}
          </p>
          {/* Desktop sort button lives here on desktop */}
          <button
            onClick={cycleSortMode}
            className="hidden md:flex items-center gap-1 px-2.5 py-1 rounded-full bg-secondary text-muted-foreground text-[11px] font-semibold whitespace-nowrap active:bg-accent transition-all"
          >
            <ArrowUpDown className="h-3 w-3" />
            {sortMode === "waiting" ? "Longest" : sortMode === "active" ? "Active" : "Newest"}
          </button>
        </div>

        {/* Search */}
        <div className="px-4 py-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search leads..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 h-9 bg-secondary border-none text-sm rounded-xl"
            />
          </div>
        </div>

        {/* Classification filter pills + mobile controls */}
        <div className="px-4 pb-1 flex gap-1.5 overflow-x-auto scrollbar-hide">
          {CLASSIFICATION_FILTERS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setClassFilter(key)}
              className={cn(
                "px-3 py-1.5 rounded-full text-[12px] font-semibold whitespace-nowrap transition-all",
                classFilter === key
                  ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                  : "bg-secondary text-muted-foreground active:bg-accent",
              )}
            >
              {label}
            </button>
          ))}
          {/* Mobile: sort + stage toggle at end of row */}
          <div className="md:hidden ml-auto flex gap-1.5 shrink-0 pl-1">
            <button
              onClick={cycleSortMode}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-full bg-secondary text-muted-foreground text-[12px] font-semibold whitespace-nowrap active:bg-accent transition-all"
            >
              <ArrowUpDown className="h-3 w-3" />
              {sortMode === "waiting" ? "Longest" : sortMode === "active" ? "Active" : "Newest"}
            </button>
            <button
              onClick={() => setStageRowOpen((s) => !s)}
              className={cn(
                "px-3 py-1.5 rounded-full text-[12px] font-semibold whitespace-nowrap transition-all",
                stageFilter !== "all" || stageRowOpen
                  ? "bg-foreground text-background"
                  : "bg-secondary text-muted-foreground active:bg-accent",
              )}
            >
              Stage{stageFilter !== "all" ? " ·" : ""}
            </button>
          </div>
        </div>

        {/* Stage filter pills — always on desktop, toggleable on mobile */}
        <div className={cn(
          "px-4 pb-2 items-center gap-1.5",
          stageRowOpen ? "flex" : "hidden md:flex",
        )}>
          <div className="flex-1 flex gap-1.5 overflow-x-auto scrollbar-hide">
            <button
              onClick={() => setStageFilter("all")}
              className={cn(
                "px-3 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap transition-all",
                stageFilter === "all"
                  ? "bg-foreground text-background"
                  : "bg-secondary text-muted-foreground active:bg-accent",
              )}
            >
              All Stages
            </button>
            {STAGES.map((stage) => (
              <button
                key={stage}
                onClick={() => setStageFilter(stage)}
                className={cn(
                  "px-3 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap transition-all",
                  stageFilter === stage
                    ? "bg-foreground text-background"
                    : "bg-secondary text-muted-foreground active:bg-accent",
                )}
              >
                {stage}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Stats cards — desktop only */}
      <div className="hidden md:grid px-4 py-3 grid-cols-4 gap-2">
        <div className="ios-card p-2.5 text-center">
          <Users className="h-4 w-4 text-primary mx-auto mb-1" />
          <p className="text-lg font-bold text-foreground leading-none">{totalLeads}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">Total</p>
        </div>
        <div className="ios-card p-2.5 text-center">
          <MessageCircle className="h-4 w-4 text-stage-new mx-auto mb-1" />
          <p className="text-lg font-bold text-foreground leading-none">{unreadCount}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">Unread</p>
        </div>
        <div className="ios-card p-2.5 text-center">
          <Clock className="h-4 w-4 text-stage-hesitant mx-auto mb-1" />
          <p className="text-lg font-bold text-foreground leading-none">{urgentCount}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">Urgent</p>
        </div>
        <div className="ios-card p-2.5 text-center">
          <TrendingUp className="h-4 w-4 text-stage-deposited mx-auto mb-1" />
          <p className="text-lg font-bold text-foreground leading-none">{depositedCount}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">Converted</p>
        </div>
      </div>

      {/* Leads list - iOS grouped table style */}
      <div className="flex-1 overflow-y-auto px-4 pb-8 md:pb-4">
        <div className="ios-card overflow-hidden divide-y divide-[hsl(var(--ios-separator))]">
          {filtered.map((lead) => {
            const urgency = getUrgencyLevel(lead.stageEnteredAt);
            return (
              <button
                key={lead.id}
                onClick={() => onSelectLead(lead.id)}
                className={cn(
                  "w-full flex items-center gap-3 px-3.5 py-3 transition-colors text-left active:bg-accent/80",
                  selectedLeadId === lead.id && "bg-accent",
                  urgency === "critical" &&
                    selectedLeadId !== lead.id &&
                    "bg-destructive/5",
                  urgency === "high" &&
                    selectedLeadId !== lead.id &&
                    "bg-stage-hesitant/5",
                )}
              >
                {/* Avatar */}
                <div className="relative shrink-0">
                  <div
                    className={cn(
                      "h-11 w-11 rounded-full bg-secondary flex items-center justify-center text-sm font-semibold text-foreground",
                      urgency === "critical" && "ring-2 ring-destructive/60",
                      urgency === "high" && "ring-2 ring-stage-hesitant/60",
                    )}
                  >
                    {lead.avatar}
                  </div>
                  {lead.unread > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 h-5 w-5 rounded-full bg-primary text-[10px] font-bold text-primary-foreground flex items-center justify-center">
                      {lead.unread}
                    </span>
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[14px] font-semibold text-foreground truncate">
                        {lead.name}
                      </span>
                      {lead.escalated && (
                        <span className="shrink-0 flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-destructive/15 text-destructive text-[10px] font-bold">
                          <AlertTriangle className="h-2.5 w-2.5" />
                          Escalated
                        </span>
                      )}
                    </div>
                    <span
                      className={cn(
                        "text-[12px] font-bold shrink-0 ml-2 tabular-nums",
                        urgency === "critical"
                          ? "text-destructive"
                          : urgency === "high"
                            ? "text-stage-hesitant"
                            : "text-muted-foreground",
                      )}
                    >
                      {formatTimeInStage(lead.stageEnteredAt)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-0.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span
                        className={cn(
                          "h-2 w-2 rounded-full shrink-0",
                          STAGE_COLORS[lead.stage],
                        )}
                      />
                      <span
                        className={cn(
                          "text-[12px] font-medium truncate",
                          STAGE_TEXT_COLORS[lead.stage],
                        )}
                      >
                        {lead.stage}
                      </span>
                    </div>
                    <span
                      className={cn(
                        "text-[10px] font-semibold shrink-0 ml-2 px-1.5 py-0.5 rounded-full",
                        classificationColor(lead.classification),
                      )}
                    >
                      {classificationLabel(lead.classification)}
                    </span>
                  </div>
                </div>

                {/* iOS chevron */}
                <svg
                  className="h-4 w-4 text-muted-foreground/30 shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
