import { useEffect, useState, useCallback } from "react";
import { Users, TrendingUp, Star, Clock, Calendar, AlertTriangle, BarChart2, Link, Trophy, Copy, Check } from "lucide-react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import {
  fetchOverview, fetchConversions, fetchStageDistribution,
  fetchHourlyHeatmap, fetchDayOfWeek, fetchLeadsOverTime,
  fetchCampaigns, fetchCampaignFlags, fetchCreatives, fetchAdAlerts, fetchTrackedCampaigns,
  createTrackedCampaign,
  Overview, ConversionMetric, StageCount, HourCount, DayCount, DayOfWeek, DateRange,
  CampaignMetric, CampaignFlag, CreativeMetric, AdAlert, TrackedCampaign,
} from "../api/analytics";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Date range helpers
// ---------------------------------------------------------------------------

function toISO(d: Date) {
  return d.toISOString().slice(0, 10);
}

const PRESETS: { label: string; range: DateRange }[] = [
  { label: "All time", range: null },
  { label: "Today", range: (() => { const t = toISO(new Date()); return { from: t, to: t }; })() },
  { label: "7D", range: { from: toISO(new Date(Date.now() - 6 * 86400000)), to: toISO(new Date()) } },
  { label: "30D", range: { from: toISO(new Date(Date.now() - 29 * 86400000)), to: toISO(new Date()) } },
  { label: "90D", range: { from: toISO(new Date(Date.now() - 89 * 86400000)), to: toISO(new Date()) } },
];

// ---------------------------------------------------------------------------
// SVG Line chart — leads over time
// ---------------------------------------------------------------------------

function LineChart({ data }: { data: DayCount[] }) {
  if (data.length === 0) {
    return <div className="flex items-center justify-center h-28 text-muted-foreground text-xs">No data yet</div>;
  }
  const W = 340; const H = 100;
  const PAD = { top: 8, right: 8, bottom: 20, left: 24 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;
  const maxVal = Math.max(...data.map((d) => d.count), 1);
  const xStep = chartW / Math.max(data.length - 1, 1);
  const pts = data.map((d, i) => ({
    x: PAD.left + i * xStep,
    y: PAD.top + chartH - (d.count / maxVal) * chartH,
    label: d.date.slice(5),
  }));
  const polyline = pts.map((p) => `${p.x},${p.y}`).join(" ");
  const fill = [`M ${pts[0].x} ${PAD.top + chartH}`, ...pts.map((p) => `L ${p.x} ${p.y}`), `L ${pts[pts.length - 1].x} ${PAD.top + chartH}`, "Z"].join(" ");
  const every = Math.ceil(data.length / 6);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 100 }}>
      {[0, 0.5, 1].map((f) => {
        const y = PAD.top + chartH * (1 - f);
        return <g key={f}>
          <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} stroke="hsl(var(--border))" strokeWidth={0.5} />
          <text x={PAD.left - 3} y={y + 4} textAnchor="end" fontSize={7} fill="hsl(var(--muted-foreground))">{Math.round(maxVal * f)}</text>
        </g>;
      })}
      <path d={fill} fill="hsl(var(--primary))" opacity={0.08} />
      <polyline points={polyline} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r={2} fill="hsl(var(--primary))" />
          {i % every === 0 && <text x={p.x} y={H - 3} textAnchor="middle" fontSize={7} fill="hsl(var(--muted-foreground))">{p.label}</text>}
        </g>
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Hourly heatmap — 24 blocks coloured by intensity
// ---------------------------------------------------------------------------

function HourlyHeatmap({ data }: { data: HourCount[] }) {
  if (data.length === 0) return <div className="text-xs text-muted-foreground text-center py-4">No data yet</div>;
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div>
      <div className="flex gap-0.5">
        {data.map((d) => {
          const intensity = d.count / max;
          const opacity = intensity === 0 ? 0.05 : 0.1 + intensity * 0.9;
          return (
            <div key={d.hour} className="flex-1 flex flex-col items-center gap-0.5" title={`${d.hour}:00 — ${d.count} msgs`}>
              <div
                className="w-full rounded-sm"
                style={{ height: 28, background: `hsl(var(--primary))`, opacity }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-1">
        <span className="text-[9px] text-muted-foreground">12am</span>
        <span className="text-[9px] text-muted-foreground">6am</span>
        <span className="text-[9px] text-muted-foreground">12pm</span>
        <span className="text-[9px] text-muted-foreground">6pm</span>
        <span className="text-[9px] text-muted-foreground">11pm</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day of week bars
// ---------------------------------------------------------------------------

function DayOfWeekChart({ data }: { data: DayOfWeek[] }) {
  if (data.length === 0) return <div className="text-xs text-muted-foreground text-center py-4">No data yet</div>;
  const maxLeads = Math.max(...data.map((d) => d.leads), 1);
  return (
    <div className="flex gap-1.5 items-end h-20">
      {data.map((d) => (
        <div key={d.day} className="flex-1 flex flex-col items-center gap-0.5">
          <div className="w-full flex flex-col justify-end gap-0.5" style={{ height: 60 }}>
            <div
              className="w-full rounded-t-sm"
              style={{
                height: `${(d.leads / maxLeads) * 56}px`,
                minHeight: d.leads > 0 ? 3 : 0,
                background: "hsl(var(--primary))",
              }}
              title={`${d.leads} leads`}
            />
            {d.deposits > 0 && (
              <div
                className="w-full rounded-t-sm"
                style={{
                  height: `${(d.deposits / maxLeads) * 56}px`,
                  minHeight: 3,
                  background: "hsl(199, 86%, 32%)",
                }}
                title={`${d.deposits} deposits`}
              />
            )}
          </div>
          <span className="text-[9px] text-muted-foreground">{d.day}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Conversion funnel donut chart
// ---------------------------------------------------------------------------

const FUNNEL_COLORS = [
  "hsl(199,86%,55%)",   // New Lead — primary blue
  "hsl(217,91%,65%)",   // Qualified — lighter blue
  "hsl(270,60%,60%)",   // Hesitant — purple
  "hsl(38,92%,55%)",    // Link Sent — amber
  "hsl(25,95%,53%)",    // Account Created — orange
  "hsl(38,92%,40%)",    // Deposit Intent — dark amber
  "hsl(142,60%,45%)",   // Deposited — green
  "hsl(43,92%,52%)",    // VIP — gold
];

function ConversionFunnel({ stages }: { stages: StageCount[] }) {
  if (stages.length === 0) {
    return <div className="flex items-center justify-center h-40 text-muted-foreground text-xs">No data yet</div>;
  }
  const total = stages.reduce((s, st) => s + st.count, 0);
  const data = stages.filter((s) => s.count > 0).map((s, i) => ({
    name: s.label,
    value: s.count,
    color: FUNNEL_COLORS[i % FUNNEL_COLORS.length],
  }));

  return (
    <div className="flex flex-col sm:flex-row items-center gap-4">
      <div className="w-40 h-40 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={42}
              outerRadius={65}
              paddingAngle={2}
              dataKey="value"
              strokeWidth={0}
            >
              {data.map((entry, i) => (
                <Cell key={i} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(220,18%,10%)",
                border: "1px solid hsl(220,14%,16%)",
                borderRadius: "8px",
                fontSize: "12px",
                color: "hsl(210,20%,92%)",
              }}
              formatter={(value: number, name: string) => [value, name]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex-1 space-y-1.5 w-full">
        {data.map((entry) => (
          <div key={entry.name} className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: entry.color }} />
              <span className="text-[11px] text-muted-foreground truncate">{entry.name}</span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-[11px] font-semibold text-foreground">{entry.value}</span>
              <span className="text-[10px] text-muted-foreground w-8 text-right">
                {total > 0 ? `${((entry.value / total) * 100).toFixed(0)}%` : "—"}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage distribution bar chart
// ---------------------------------------------------------------------------

function StageDistribution({ stages }: { stages: StageCount[] }) {
  const max = Math.max(...stages.map((s) => s.count), 1);
  return (
    <div className="space-y-1.5">
      {stages.map((s, i) => (
        <div key={s.stage} className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground w-28 truncate shrink-0">{s.label}</span>
          <div className="flex-1 h-2 bg-secondary rounded-full overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{
                width: `${(s.count / max) * 100}%`,
                background: FUNNEL_COLORS[i % FUNNEL_COLORS.length],
              }}
            />
          </div>
          <span className="text-[11px] font-bold text-foreground w-4 text-right shrink-0">{s.count}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Conversion metrics table
// ---------------------------------------------------------------------------

function ConversionTable({ metrics }: { metrics: ConversionMetric[] }) {
  return (
    <div className="divide-y divide-[hsl(var(--ios-separator))]">
      {metrics.map((m) => {
        const rate = m.rate ?? 0;
        const hitting = rate >= m.target;
        return (
          <div key={m.label} className="flex items-center gap-3 py-2.5">
            <div className="flex-1 min-w-0">
              <p className="text-[12px] font-semibold text-foreground">{m.label}</p>
              <p className="text-[10px] text-muted-foreground">
                {m.to_entries} of {m.from_entries} entries · target &gt;{m.target}%
              </p>
            </div>
            <div className="shrink-0 text-right">
              <span className={cn(
                "text-[15px] font-bold",
                m.rate === null ? "text-muted-foreground" :
                hitting ? "text-primary" : "text-destructive"
              )}>
                {m.rate === null ? "—" : `${rate}%`}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function AnalyticsDashboard() {
  const [range, setRange] = useState<DateRange>(PRESETS[3].range); // default 30D
  const [activePreset, setActivePreset] = useState(3);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const [overview, setOverview] = useState<Overview | null>(null);
  const [conversions, setConversions] = useState<ConversionMetric[]>([]);
  const [stages, setStages] = useState<StageCount[]>([]);
  const [hourly, setHourly] = useState<HourCount[]>([]);
  const [dow, setDow] = useState<DayOfWeek[]>([]);
  const [leadsOverTime, setLeadsOverTime] = useState<DayCount[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignMetric[]>([]);
  const [campaignFlags, setCampaignFlags] = useState<CampaignFlag[]>([]);
  const [creatives, setCreatives] = useState<CreativeMetric[]>([]);
  const [adAlerts, setAdAlerts] = useState<AdAlert[]>([]);
  const [trackedCampaigns, setTrackedCampaigns] = useState<TrackedCampaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newCampaignName, setNewCampaignName] = useState("");
  const [newCampaignMetaId, setNewCampaignMetaId] = useState("");
  const [creatingCampaign, setCreatingCampaign] = useState(false);
  const [copiedTag, setCopiedTag] = useState<string | null>(null);

  const load = useCallback((r: DateRange) => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchOverview(r),
      fetchConversions(r),
      fetchStageDistribution(),
      fetchHourlyHeatmap(r),
      fetchDayOfWeek(r),
      fetchLeadsOverTime(r),
      fetchCampaigns(r),
      fetchCampaignFlags(),
      fetchCreatives(r),
      fetchAdAlerts(),
      fetchTrackedCampaigns(),
    ])
      .then(([ov, cv, sg, hr, dw, lt, camp, flags, creat, alerts, tracked]) => {
        setOverview(ov);
        setConversions(cv);
        setStages(sg);
        setHourly(hr);
        setDow(dw);
        setLeadsOverTime(lt);
        setCampaigns(camp);
        setCampaignFlags(flags);
        setCreatives(creat);
        setAdAlerts(alerts);
        setTrackedCampaigns(tracked);
      })
      .catch((e) => setError(e?.message || "Failed to load analytics"))
      .finally(() => setLoading(false));
  }, []);

  const handleCreateCampaign = useCallback(async () => {
    if (!newCampaignName.trim()) return;
    setCreatingCampaign(true);
    try {
      const created = await createTrackedCampaign(newCampaignName.trim(), newCampaignMetaId.trim() || undefined);
      setTrackedCampaigns((prev) => [created, ...prev]);
      setNewCampaignName("");
      setNewCampaignMetaId("");
    } catch (e: any) {
      setError(e?.message || "Failed to create campaign");
    } finally {
      setCreatingCampaign(false);
    }
  }, [newCampaignName, newCampaignMetaId]);

  const handleCopyLink = useCallback((link: string, tag: string) => {
    navigator.clipboard.writeText(link).then(() => {
      setCopiedTag(tag);
      setTimeout(() => setCopiedTag(null), 2000);
    });
  }, []);

  useEffect(() => { load(range); }, []);

  function applyPreset(idx: number) {
    setActivePreset(idx);
    setCustomFrom("");
    setCustomTo("");
    setRange(PRESETS[idx].range);
    load(PRESETS[idx].range);
  }

  function applyCustomRange() {
    if (!customFrom || !customTo) return;
    const r: DateRange = { from: customFrom, to: customTo };
    setRange(r);
    setActivePreset(-1);
    load(r);
  }

  if (loading) return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading analytics...</div>;
  if (error) return <div className="flex-1 flex items-center justify-center text-destructive text-sm">{error}</div>;

  return (
    <div className="flex-1 overflow-y-auto px-4 pb-8 space-y-4 pt-3">

      {/* Date range picker */}
      <div className="ios-card p-3 space-y-2">
        {/* Preset pills */}
        <div className="flex gap-1.5 overflow-x-auto scrollbar-hide">
          {PRESETS.map((p, i) => (
            <button
              key={p.label}
              onClick={() => applyPreset(i)}
              className={cn(
                "px-3 py-1.5 rounded-full text-[12px] font-semibold whitespace-nowrap transition-all",
                activePreset === i
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "bg-secondary text-muted-foreground active:bg-accent"
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        {/* Custom range inputs */}
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={customFrom}
            onChange={(e) => setCustomFrom(e.target.value)}
            className="flex-1 text-[12px] bg-secondary rounded-lg px-2 py-1.5 text-foreground border-none outline-none"
          />
          <span className="text-[11px] text-muted-foreground shrink-0">to</span>
          <input
            type="date"
            value={customTo}
            onChange={(e) => setCustomTo(e.target.value)}
            className="flex-1 text-[12px] bg-secondary rounded-lg px-2 py-1.5 text-foreground border-none outline-none"
          />
          <button
            onClick={applyCustomRange}
            disabled={!customFrom || !customTo}
            className="px-3 py-1.5 rounded-lg text-[12px] font-semibold bg-primary text-primary-foreground disabled:opacity-40 shrink-0"
          >
            Apply
          </button>
        </div>
        {range && (
          <p className="text-[10px] text-muted-foreground">
            Showing: {range.from} → {range.to}
          </p>
        )}
      </div>

      {/* Overview cards */}
      <div className="grid grid-cols-2 gap-2">
        <div className="ios-card p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <Users className="h-3.5 w-3.5 text-primary" />
            <span className="text-[11px] text-muted-foreground font-medium">Total Leads</span>
          </div>
          <p className="text-2xl font-bold text-foreground">{overview?.total_leads ?? 0}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">+{overview?.new_today ?? 0} today · +{overview?.new_this_week ?? 0} this week</p>
        </div>

        <div className="ios-card p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <Star className="h-3.5 w-3.5 text-stage-deposited" />
            <span className="text-[11px] text-muted-foreground font-medium">Deposited</span>
          </div>
          <p className="text-2xl font-bold text-foreground">{overview?.total_deposited ?? 0}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">ever reached stage 7</p>
        </div>

        <div className="ios-card p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingUp className="h-3.5 w-3.5 text-stage-qualified" />
            <span className="text-[11px] text-muted-foreground font-medium">1→7 Conversion</span>
          </div>
          <p className={cn("text-2xl font-bold", (overview?.overall_conversion ?? 0) >= 10 ? "text-primary" : "text-destructive")}>
            {overview?.overall_conversion ?? 0}%
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">target &gt;10%</p>
        </div>

        <div className="ios-card p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <Clock className="h-3.5 w-3.5 text-stage-hesitant" />
            <span className="text-[11px] text-muted-foreground font-medium">Avg Days to Deposit</span>
          </div>
          <p className={cn("text-2xl font-bold", overview?.avg_days_to_deposit == null ? "text-muted-foreground" : (overview.avg_days_to_deposit <= 5 ? "text-primary" : "text-destructive"))}>
            {overview?.avg_days_to_deposit != null ? `${overview.avg_days_to_deposit}d` : "—"}
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">target &lt;5 days</p>
        </div>
      </div>

      {/* Conversion metrics */}
      <div className="ios-card p-3">
        <h2 className="text-[13px] font-semibold text-foreground mb-1">Conversion Metrics</h2>
        <p className="text-[10px] text-muted-foreground mb-3">Green = hitting target · Red = below target</p>
        <ConversionTable metrics={conversions} />
      </div>

      {/* Stage distribution + funnel donut */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="ios-card p-4">
          <h2 className="text-[13px] font-semibold text-foreground mb-4">Conversion Funnel</h2>
          <ConversionFunnel stages={stages} />
        </div>
        <div className="ios-card p-4">
          <h2 className="text-[13px] font-semibold text-foreground mb-3">Leads by Stage</h2>
          <StageDistribution stages={stages} />
        </div>
      </div>

      {/* Leads over time */}
      <div className="ios-card p-3">
        <h2 className="text-[13px] font-semibold text-foreground mb-2">New Leads — Last 30 Days</h2>
        <LineChart data={leadsOverTime} />
      </div>

      {/* Hourly heatmap */}
      <div className="ios-card p-3">
        <div className="flex items-center gap-1.5 mb-3">
          <Clock className="h-3.5 w-3.5 text-primary" />
          <h2 className="text-[13px] font-semibold text-foreground">Peak Engagement Hours</h2>
        </div>
        <p className="text-[10px] text-muted-foreground mb-2">Inbound messages by hour of day (Dubai time)</p>
        <HourlyHeatmap data={hourly} />
      </div>

      {/* Day of week */}
      <div className="ios-card p-3">
        <div className="flex items-center gap-1.5 mb-1">
          <Calendar className="h-3.5 w-3.5 text-primary" />
          <h2 className="text-[13px] font-semibold text-foreground">Day of Week</h2>
        </div>
        <div className="flex items-center gap-3 mb-3">
          <div className="flex items-center gap-1"><div className="h-2 w-3 rounded-sm" style={{ background: "hsl(var(--primary))" }} /><span className="text-[10px] text-muted-foreground">Leads</span></div>
          <div className="flex items-center gap-1"><div className="h-2 w-3 rounded-sm" style={{ background: "hsl(199, 86%, 32%)" }} /><span className="text-[10px] text-muted-foreground">Deposits</span></div>
        </div>
        <DayOfWeekChart data={dow} />
      </div>

      {/* ── Phase 4: Ad Intelligence ───────────────────────────────────── */}

      {/* Alert banners — spend / CPL / CPD threshold breaches */}
      {adAlerts.length > 0 && (
        <div className="space-y-2">
          {adAlerts.map((a, i) => (
            <div
              key={i}
              className={cn(
                "flex items-start gap-2.5 rounded-xl px-3 py-2.5 border",
                a.severity === "critical"
                  ? "bg-destructive/8 border-destructive/30"
                  : "bg-[hsl(38,92%,52%)/8] border-[hsl(38,92%,52%)/30]"
              )}
            >
              <AlertTriangle className={cn("h-3.5 w-3.5 mt-0.5 shrink-0", a.severity === "critical" ? "text-destructive" : "text-[hsl(38,92%,52%)]")} />
              <div className="min-w-0">
                <p className={cn("text-[12px] font-semibold", a.severity === "critical" ? "text-destructive" : "text-[hsl(38,92%,58%)]")}>
                  {a.type === "cpd" ? "CPD Alert" : a.type === "cpl" ? "CPL Alert" : "Spend Alert"}
                </p>
                <p className="text-[11px] text-muted-foreground truncate">{a.campaign_name} · {a.message}</p>
              </div>
              <span className={cn("text-[13px] font-bold shrink-0 ml-auto", a.severity === "critical" ? "text-destructive" : "text-[hsl(38,92%,58%)]")}>
                €{a.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Underperforming campaign flags — CPD > €200 for 3+ days */}
      {campaignFlags.length > 0 && (
        <div className="ios-card p-3 border border-destructive/30 bg-destructive/5">
          <div className="flex items-center gap-1.5 mb-2">
            <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
            <h2 className="text-[13px] font-semibold text-destructive">Underperforming Campaigns</h2>
          </div>
          <p className="text-[10px] text-muted-foreground mb-2">CPD &gt; €200 for 3+ consecutive days</p>
          <div className="space-y-2">
            {campaignFlags.map((f) => (
              <div key={f.campaign_id} className="flex items-center justify-between gap-2 bg-destructive/10 rounded-xl px-3 py-2">
                <div className="min-w-0">
                  <p className="text-[12px] font-semibold text-foreground truncate">{f.campaign_name}</p>
                  <p className="text-[10px] text-muted-foreground">{f.consecutive_days} consecutive days over limit</p>
                </div>
                <span className="text-[13px] font-bold text-destructive shrink-0">€{f.latest_cpd}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Campaign performance table */}
      <div className="ios-card p-3">
        <div className="flex items-center gap-1.5 mb-1">
          <BarChart2 className="h-3.5 w-3.5 text-primary" />
          <h2 className="text-[13px] font-semibold text-foreground">Ad Campaign Performance</h2>
        </div>
        <p className="text-[10px] text-muted-foreground mb-3">Spend attributed via Telegram /start tag · CPD target &lt;€150</p>
        {campaigns.length === 0 ? (
          <p className="text-[12px] text-muted-foreground text-center py-4">No campaign data yet — connect Meta API to populate</p>
        ) : (
          <div className="divide-y divide-[hsl(var(--ios-separator))]">
            <div className="flex items-center gap-2 pb-1.5">
              <span className="flex-1 text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">Campaign</span>
              <span className="w-14 text-right text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">Spend</span>
              <span className="w-10 text-right text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">CPL</span>
              <span className="w-10 text-right text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">CPD</span>
            </div>
            {campaigns.map((c) => (
              <div key={c.campaign_id} className="flex items-center gap-2 py-2.5">
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-semibold text-foreground truncate">{c.campaign_name}</p>
                  <p className="text-[10px] text-muted-foreground">
                    {c.leads} leads · {c.deposits} deposits · {c.impressions.toLocaleString()} impressions
                  </p>
                </div>
                <span className="w-14 text-right text-[12px] font-bold text-foreground">€{c.spend.toFixed(0)}</span>
                <span className="w-10 text-right text-[12px] font-bold text-muted-foreground">
                  {c.cpl !== null ? `€${c.cpl}` : "—"}
                </span>
                <span className={cn("w-10 text-right text-[12px] font-bold",
                  c.cpd !== null && c.cpd > 150 ? "text-destructive" :
                  c.cpd !== null ? "text-stage-deposited" : "text-muted-foreground"
                )}>
                  {c.cpd !== null ? `€${c.cpd}` : "—"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Best performing creative leaderboard */}
      <div className="ios-card p-3">
        <div className="flex items-center gap-1.5 mb-1">
          <Trophy className="h-3.5 w-3.5 text-[hsl(43,92%,52%)]" />
          <h2 className="text-[13px] font-semibold text-foreground">Best Performing Creatives</h2>
        </div>
        <p className="text-[10px] text-muted-foreground mb-3">Sorted by cost per deposit · lowest = best</p>
        {creatives.length === 0 ? (
          <p className="text-[12px] text-muted-foreground text-center py-4">No creative data yet — connect Meta API to populate</p>
        ) : (
          <div className="divide-y divide-[hsl(var(--ios-separator))]">
            {creatives.map((c, i) => (
              <div key={c.ad_id} className="flex items-center gap-2 py-2.5">
                <span className={cn("text-[11px] font-bold w-5 shrink-0",
                  i === 0 ? "text-[hsl(43,92%,52%)]" : "text-muted-foreground"
                )}>#{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-semibold text-foreground truncate">{c.ad_name}</p>
                  <p className="text-[10px] text-muted-foreground truncate">{c.campaign_name}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className={cn("text-[13px] font-bold",
                    c.cpd !== null && c.cpd <= 150 ? "text-stage-deposited" :
                    c.cpd !== null ? "text-destructive" : "text-muted-foreground"
                  )}>
                    {c.cpd !== null ? `€${c.cpd}` : "—"}
                  </p>
                  <p className="text-[10px] text-muted-foreground">{c.deposits} deposits · €{c.spend.toFixed(0)} spend</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tracked URL generator */}
      <div className="ios-card p-3">
        <div className="flex items-center gap-1.5 mb-1">
          <Link className="h-3.5 w-3.5 text-primary" />
          <h2 className="text-[13px] font-semibold text-foreground">Tracked Campaign Links</h2>
        </div>
        <p className="text-[10px] text-muted-foreground mb-3">Generate a unique Telegram link per Meta ad campaign for full attribution</p>

        {/* Generator form */}
        <div className="space-y-2 mb-4">
          <input
            type="text"
            value={newCampaignName}
            onChange={(e) => setNewCampaignName(e.target.value)}
            placeholder="Campaign name (e.g. UAE Lookalike Oct)"
            className="w-full bg-secondary rounded-xl px-3 py-2 text-[12px] text-foreground placeholder-muted-foreground outline-none focus:ring-1 focus:ring-primary border-none"
          />
          <input
            type="text"
            value={newCampaignMetaId}
            onChange={(e) => setNewCampaignMetaId(e.target.value)}
            placeholder="Meta campaign ID (optional)"
            className="w-full bg-secondary rounded-xl px-3 py-2 text-[12px] text-foreground placeholder-muted-foreground outline-none focus:ring-1 focus:ring-primary border-none"
          />
          <button
            onClick={handleCreateCampaign}
            disabled={!newCampaignName.trim() || creatingCampaign}
            className="w-full bg-primary text-primary-foreground font-semibold text-[12px] py-2 rounded-xl disabled:opacity-40 transition-opacity"
          >
            {creatingCampaign ? "Generating…" : "Generate Tracked Link"}
          </button>
        </div>

        {/* Existing tracked campaigns */}
        {trackedCampaigns.length > 0 && (
          <div className="divide-y divide-[hsl(var(--ios-separator))]">
            {trackedCampaigns.map((c) => (
              <div key={c.source_tag} className="py-2.5 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[12px] font-semibold text-foreground truncate">{c.name}</p>
                  <span className="text-[10px] text-muted-foreground shrink-0">{c.leads}L · {c.deposits}D</span>
                </div>

                {/* Landing page URL — paste this into the Meta ad */}
                {c.landing_url ? (
                  <div>
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground font-semibold mb-0.5">Landing URL — paste into Meta ad</p>
                    <div className="flex items-center gap-2 bg-secondary rounded-lg px-2.5 py-1.5">
                      <p className="flex-1 text-[10px] text-muted-foreground truncate font-mono">{c.landing_url}</p>
                      <button
                        onClick={() => handleCopyLink(c.landing_url!, c.source_tag + "_landing")}
                        className="shrink-0 text-primary"
                      >
                        {copiedTag === c.source_tag + "_landing"
                          ? <Check className="h-3.5 w-3.5" />
                          : <Copy className="h-3.5 w-3.5" />
                        }
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="text-[10px] text-muted-foreground italic">Set your Landing Page URL in Settings → Meta Ads to generate tracked landing links.</p>
                )}

                {/* Direct bot link — use if skipping landing page */}
                {c.link && (
                  <div>
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground font-semibold mb-0.5">Direct bot link</p>
                    <div className="flex items-center gap-2 bg-secondary rounded-lg px-2.5 py-1.5">
                      <p className="flex-1 text-[10px] text-muted-foreground truncate font-mono">{c.link}</p>
                      <button
                        onClick={() => handleCopyLink(c.link!, c.source_tag)}
                        className="shrink-0 text-primary"
                      >
                        {copiedTag === c.source_tag
                          ? <Check className="h-3.5 w-3.5" />
                          : <Copy className="h-3.5 w-3.5" />
                        }
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
}
