import { useEffect, useState } from "react";
import { fetchStageDistribution, StageCount } from "@/api/analytics";

// Colors mapped to our real backend stage labels
const STAGE_COLOR: Record<string, string> = {
  "New Lead":             "bg-stage-new",
  "Qualified":            "bg-stage-qualified",
  "Hesitant / Ghosting":  "bg-stage-hesitant",
  "Link Sent":            "bg-stage-link-sent",
  "Account Created":      "bg-stage-link-sent",
  "Deposit Intent":       "bg-warning",
  "Deposited":            "bg-success",
  "VIP Member":           "bg-primary",
};

const PipelinePreview = () => {
  const [stages, setStages] = useState<StageCount[]>([]);

  useEffect(() => {
    fetchStageDistribution().then(setStages).catch(() => {});
  }, []);

  const max = Math.max(...stages.map((s) => s.count), 1);

  return (
    <div className="surface-card p-5 md:p-6">
      <h3 className="text-sm font-semibold text-foreground mb-4">Pipeline overview</h3>
      {stages.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-10">No data yet</p>
      ) : (
        <div className="space-y-2.5">
          {stages.map((stage) => {
            const color = STAGE_COLOR[stage.label] || "bg-muted";
            return (
              <div key={stage.stage} className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground w-28 shrink-0 truncate">{stage.label}</span>
                <div className="flex-1 h-6 bg-secondary/60 rounded-md overflow-hidden">
                  <div
                    className={`h-full ${color} rounded-md flex items-center px-2 transition-all duration-500`}
                    style={{ width: `${Math.max((stage.count / max) * 100, stage.count > 0 ? 8 : 0)}%` }}
                  >
                    <span className="text-[11px] font-semibold text-white tabular-nums">{stage.count}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default PipelinePreview;
