import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchContacts } from "@/api/crm";
import { Lead } from "@/data/crmData";

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
    <div className="surface-card p-5 md:p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-foreground">Recent leads</h3>
        <button onClick={() => navigate("/leads")} className="text-xs text-primary hover:text-primary/80 transition-colors">
          View all →
        </button>
      </div>
      {leads.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-8">No leads yet</p>
      ) : (
        <div className="-mx-2">
          {leads.map((lead) => {
            const initials = (lead.name || lead.username || "?")
              .split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();
            return (
              <button
                key={lead.id}
                onClick={() => navigate("/leads")}
                className="w-full flex items-center justify-between gap-3 px-2 py-2.5 rounded-lg hover:bg-secondary/50 transition-colors text-left"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-[11px] font-semibold text-primary shrink-0">
                    {initials}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{lead.name || lead.username || "Unknown"}</p>
                    <p className="text-xs text-muted-foreground truncate">@{lead.username}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="text-xs font-medium text-muted-foreground">{lead.stageName}</span>
                  <span className="text-xs text-muted-foreground w-12 text-right tabular-nums">{timeAgo(lead.lastMessageAt)}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default RecentLeads;
