import { Search, Users, Clock, TrendingUp, MessageCircle } from "lucide-react";
import { Input } from "../ui/input";
import { useState } from "react";
import { Lead, STAGE_COLORS, STAGE_TEXT_COLORS, formatTimeInStage, classificationLabel, classificationColor } from "../../data/crmData";
import { cn } from "../../lib/utils";

interface LeadListProps {
  leads: Lead[];
  selectedLeadId: string | null;
  onSelectLead: (id: string) => void;
}

function getUrgencyLevel(stageEnteredAt: string): "critical" | "high" | "normal" {
  const now = new Date();
  const hrs = (now.getTime() - new Date(stageEnteredAt).getTime()) / 3600000;
  if (hrs >= 48) return "critical";
  if (hrs >= 12) return "high";
  return "normal";
}

type ClassificationFilter = "all" | "new_lead" | "warm_lead" | "vip" | "affiliate" | "noise";

const CLASSIFICATION_FILTERS: { key: ClassificationFilter; label: string }[] = [
  { key: "all",       label: "All" },
  { key: "warm_lead", label: "Warm Lead" },
  { key: "vip",       label: "VIP" },
  { key: "affiliate", label: "Affiliate" },
  { key: "noise",     label: "Noise" },
];

export function LeadList({ leads, selectedLeadId, onSelectLead }: LeadListProps) {
  const [search, setSearch] = useState("");
  const [classFilter, setClassFilter] = useState<ClassificationFilter>("all");

  const filtered = leads
    .filter((l) => {
      // Noise contacts are only shown when the Noise tab is explicitly selected
      if (classFilter === "all" && l.classification === "noise") return false;
      if (classFilter !== "all" && l.classification !== classFilter) return false;
      if (search && !l.name.toLowerCase().includes(search.toLowerCase()) && !l.username.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    })
    .sort((a, b) => new Date(a.stageEnteredAt).getTime() - new Date(b.stageEnteredAt).getTime());

  // Stats
  const totalLeads = leads.length;
  const unreadCount = leads.filter(l => l.unread > 0).length;
  const urgentCount = leads.filter(l => getUrgencyLevel(l.stageEnteredAt) !== "normal").length;
  const depositedCount = leads.filter(l => l.stage === "Deposited" || l.stage === "VIP Member" || l.classification === "vip").length;

  return (
    <div className="flex flex-col h-full bg-[hsl(var(--ios-grouped-bg))]">
      {/* iOS-style header */}
      <div className="safe-top bg-card/80 backdrop-blur-xl sticky top-0 z-10">
        <div className="px-4 pt-3 pb-1">
          <h1 className="text-2xl font-bold text-foreground tracking-tight">Leads</h1>
          <p className="text-xs text-muted-foreground mt-0.5">{totalLeads} total · {unreadCount} unread</p>
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

        {/* Classification filter pills */}
        <div className="px-4 pb-2 flex gap-1.5 overflow-x-auto scrollbar-hide">
          {CLASSIFICATION_FILTERS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setClassFilter(key)}
              className={cn(
                "px-3 py-1.5 rounded-full text-[12px] font-semibold whitespace-nowrap transition-all",
                classFilter === key
                  ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20"
                  : "bg-secondary text-muted-foreground active:bg-accent"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Stats cards - iOS grouped style */}
      <div className="px-4 py-3 grid grid-cols-4 gap-2">
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
      <div className="flex-1 overflow-y-auto px-4 pb-4">
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
                  urgency === "critical" && selectedLeadId !== lead.id && "bg-destructive/5",
                  urgency === "high" && selectedLeadId !== lead.id && "bg-stage-hesitant/5"
                )}
              >
                {/* Avatar */}
                <div className="relative shrink-0">
                  <div className={cn(
                    "h-11 w-11 rounded-full bg-secondary flex items-center justify-center text-sm font-semibold text-foreground",
                    urgency === "critical" && "ring-2 ring-destructive/60",
                    urgency === "high" && "ring-2 ring-stage-hesitant/60"
                  )}>
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
                    <span className="text-[14px] font-semibold text-foreground truncate">{lead.name}</span>
                    <span className={cn(
                      "text-[12px] font-bold shrink-0 ml-2 tabular-nums",
                      urgency === "critical" ? "text-destructive" :
                      urgency === "high" ? "text-stage-hesitant" :
                      "text-muted-foreground"
                    )}>
                      {formatTimeInStage(lead.stageEnteredAt)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-0.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className={cn("h-2 w-2 rounded-full shrink-0", STAGE_COLORS[lead.stage])} />
                      <span className={cn("text-[12px] font-medium truncate", STAGE_TEXT_COLORS[lead.stage])}>
                        {lead.stage}
                      </span>
                    </div>
                    <span className={cn("text-[10px] font-semibold shrink-0 ml-2 px-1.5 py-0.5 rounded-full", classificationColor(lead.classification))}>
                      {classificationLabel(lead.classification)}
                    </span>
                  </div>
                </div>

                {/* iOS chevron */}
                <svg className="h-4 w-4 text-muted-foreground/30 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
