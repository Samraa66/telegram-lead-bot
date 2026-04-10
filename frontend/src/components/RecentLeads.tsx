import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchContacts } from "@/api/crm";
import { Lead, STAGE_TEXT_COLORS, Stage } from "@/data/crmData";

const RecentLeads = () => {
  const [leads, setLeads] = useState<Lead[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    fetchContacts(true).then((all) => {
      const sorted = [...all].sort((a, b) =>
        new Date(b.lastMessageAt || 0).getTime() - new Date(a.lastMessageAt || 0).getTime()
      );
      setLeads(sorted.slice(0, 5));
    }).catch(() => {});
  }, []);

  function timeAgo(dateStr: string): string {
    const diff = Date.now() - new Date(dateStr).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  return (
    <div className="glass-card rounded-xl p-6">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-sm font-semibold text-foreground">Recent Leads</h3>
        <button onClick={() => navigate("/leads")} className="text-xs text-primary hover:underline">
          View all
        </button>
      </div>
      {leads.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-6">No leads yet</p>
      ) : (
        <div className="space-y-1">
          {leads.map((lead) => {
            const textColor = STAGE_TEXT_COLORS[lead.stage as Stage] || "text-muted-foreground";
            const initials = (lead.name || lead.username || "?")
              .split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();
            return (
              <div key={lead.id} className="flex items-center justify-between py-2.5 border-b border-border/50 last:border-0">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-semibold text-primary shrink-0">
                    {initials}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-foreground">{lead.name || lead.username || "Unknown"}</p>
                    <p className="text-xs text-muted-foreground">@{lead.username}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-medium ${textColor}`}>{lead.stage}</span>
                  <span className="text-xs text-muted-foreground w-14 text-right">{timeAgo(lead.lastMessageAt)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default RecentLeads;
