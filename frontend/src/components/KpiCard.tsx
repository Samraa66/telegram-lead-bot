import { LucideIcon } from "lucide-react";

interface KpiCardProps {
  title: string;
  value: string;
  change?: string;
  changeType?: "positive" | "negative" | "neutral";
  icon: LucideIcon;
}

const KpiCard = ({ title, value, change, changeType = "neutral", icon: Icon }: KpiCardProps) => {
  const changeStyle =
    changeType === "positive"
      ? { color: "#34d399" }
      : changeType === "negative"
      ? { color: "hsl(var(--destructive))" }
      : { color: "hsl(var(--muted-foreground))" };

  return (
    <div className="glass-card rounded-xl p-5 hover:border-primary/20 transition-all duration-300">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-muted-foreground font-medium">{title}</span>
        <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
          <Icon className="w-4 h-4 text-primary" />
        </div>
      </div>
      <p className="text-2xl font-bold text-foreground">{value}</p>
      {change && <p className="text-xs mt-1" style={changeStyle}>{change}</p>}
    </div>
  );
};

export default KpiCard;
