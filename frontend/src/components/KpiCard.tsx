import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface KpiCardProps {
  title: string;
  value: string;
  change?: string;
  changeType?: "positive" | "negative" | "neutral";
  icon: LucideIcon;
}

const KpiCard = ({ title, value, change, changeType = "neutral", icon: Icon }: KpiCardProps) => {
  const changeClass =
    changeType === "positive" ? "text-success"
    : changeType === "negative" ? "text-destructive"
    : "text-muted-foreground";

  return (
    <div className="surface-card-interactive p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{title}</span>
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
          <Icon className="w-4 h-4 text-primary" />
        </div>
      </div>
      <p className="text-2xl font-semibold text-foreground tabular-nums tracking-tight">{value}</p>
      {change && <p className={cn("text-xs mt-1.5", changeClass)}>{change}</p>}
    </div>
  );
};

export default KpiCard;
