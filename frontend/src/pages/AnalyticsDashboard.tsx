import { useEffect, useState, useCallback } from "react";
import { Users, TrendingUp, Star, Clock, Calendar } from "lucide-react";
import {
  fetchOverview, fetchConversions, fetchStageDistribution,
  fetchHourlyHeatmap, fetchDayOfWeek, fetchLeadsOverTime,
  Overview, ConversionMetric, StageCount, HourCount, DayCount, DayOfWeek, DateRange,
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
              className="w-full rounded-t-sm bg-primary"
              style={{ height: `${(d.leads / maxLeads) * 56}px`, minHeight: d.leads > 0 ? 3 : 0, opacity: 0.7 }}
              title={`${d.leads} leads`}
            />
            {d.deposits > 0 && (
              <div
                className="w-full rounded-t-sm bg-stage-deposited"
                style={{ height: `${(d.deposits / maxLeads) * 56}px`, minHeight: 3 }}
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
// Stage distribution bar chart
// ---------------------------------------------------------------------------

function StageDistribution({ stages }: { stages: StageCount[] }) {
  const max = Math.max(...stages.map((s) => s.count), 1);
  return (
    <div className="space-y-1.5">
      {stages.map((s) => (
        <div key={s.stage} className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground w-28 truncate shrink-0">{s.label}</span>
          <div className="flex-1 h-2 bg-secondary rounded-full overflow-hidden">
            <div
              className={cn("h-full rounded-full", s.stage >= 7 ? "bg-stage-deposited" : "bg-primary")}
              style={{ width: `${(s.count / max) * 100}%` }}
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
                hitting ? "text-stage-deposited" : "text-destructive"
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    ])
      .then(([ov, cv, sg, hr, dw, lt]) => {
        setOverview(ov);
        setConversions(cv);
        setStages(sg);
        setHourly(hr);
        setDow(dw);
        setLeadsOverTime(lt);
      })
      .catch((e) => setError(e?.message || "Failed to load analytics"))
      .finally(() => setLoading(false));
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
          <p className={cn("text-2xl font-bold", (overview?.overall_conversion ?? 0) >= 10 ? "text-stage-deposited" : "text-destructive")}>
            {overview?.overall_conversion ?? 0}%
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">target &gt;10%</p>
        </div>

        <div className="ios-card p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <Clock className="h-3.5 w-3.5 text-stage-hesitant" />
            <span className="text-[11px] text-muted-foreground font-medium">Avg Days to Deposit</span>
          </div>
          <p className={cn("text-2xl font-bold", overview?.avg_days_to_deposit == null ? "text-muted-foreground" : (overview.avg_days_to_deposit <= 5 ? "text-stage-deposited" : "text-destructive"))}>
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

      {/* Stage distribution */}
      <div className="ios-card p-3">
        <h2 className="text-[13px] font-semibold text-foreground mb-3">Current Leads by Stage</h2>
        <StageDistribution stages={stages} />
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
          <div className="flex items-center gap-1"><div className="h-2 w-3 rounded-sm bg-primary opacity-70" /><span className="text-[10px] text-muted-foreground">Leads</span></div>
          <div className="flex items-center gap-1"><div className="h-2 w-3 rounded-sm bg-stage-deposited" /><span className="text-[10px] text-muted-foreground">Deposits</span></div>
        </div>
        <DayOfWeekChart data={dow} />
      </div>

    </div>
  );
}
