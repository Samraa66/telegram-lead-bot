import { useEffect, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { fetchLeadsOverTime, DayCount } from "@/api/analytics";

const DepositsChart = () => {
  const [data, setData] = useState<{ day: string; leads: number }[]>([]);

  useEffect(() => {
    fetchLeadsOverTime(null).then((raw: DayCount[]) => {
      // Show last 7 days
      const last7 = raw.slice(-7).map((d) => ({
        day: new Date(d.date).toLocaleDateString("en", { weekday: "short" }),
        leads: d.count,
      }));
      setData(last7);
    }).catch(() => {});
  }, []);

  return (
    <div className="glass-card rounded-xl p-6">
      <h3 className="text-sm font-semibold text-foreground mb-5">New Leads This Week</h3>
      {data.length === 0 ? (
        <div className="flex items-center justify-center h-[220px] text-muted-foreground text-xs">No data yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={data}>
            <defs>
              <linearGradient id="leadsGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(199, 86%, 55%)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="hsl(199, 86%, 55%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 14%, 16%)" />
            <XAxis dataKey="day" tick={{ fill: "hsl(215, 12%, 55%)", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "hsl(215, 12%, 55%)", fontSize: 12 }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(220, 18%, 10%)",
                border: "1px solid hsl(220, 14%, 16%)",
                borderRadius: "8px",
                color: "hsl(210, 20%, 92%)",
                fontSize: "12px",
              }}
              formatter={(value: number) => [value, "Leads"]}
            />
            <Area type="monotone" dataKey="leads" stroke="hsl(199, 86%, 55%)" fill="url(#leadsGradient)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
};

export default DepositsChart;
