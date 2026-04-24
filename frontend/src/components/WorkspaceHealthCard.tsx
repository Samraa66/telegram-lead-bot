import { useEffect, useState, useCallback, useRef } from "react";
import { RefreshCw } from "lucide-react";
import { getToken } from "@/api/auth";
import { cn } from "@/lib/utils";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

type Status = "ok" | "warn" | "error";
type Overall = "healthy" | "degraded" | "critical";

type Check = {
  id: string;
  label: string;
  status: Status;
  detail: string;
  action?: string;
};

type Health = { overall: Overall; checks: Check[] };

// ---------------------------------------------------------------------------
// LED — a real hardware-style status light with glowing halo
// ---------------------------------------------------------------------------

const LED_RGB: Record<Status, { core: string; halo: string; anim: string }> = {
  ok:    { core: "16,185,129",  halo: "16,185,129",  anim: "led-ok"    },
  warn:  { core: "245,158,11",  halo: "245,158,11",  anim: "led-warn"  },
  error: { core: "239,68,68",   halo: "239,68,68",   anim: "led-error" },
};

function LED({ status, size = "md" }: { status: Status; size?: "md" | "lg" }) {
  const c = LED_RGB[status];
  const dim = size === "lg" ? 14 : 10;
  return (
    <span
      aria-hidden
      className="shrink-0 inline-block rounded-full"
      style={{
        width: dim,
        height: dim,
        background: `radial-gradient(circle at 32% 28%, rgba(255,255,255,0.75) 0%, rgba(255,255,255,0) 45%), rgb(${c.core})`,
        boxShadow: `
          0 0 0 1px rgba(${c.halo}, 0.35),
          0 0 ${size === "lg" ? 18 : 12}px rgba(${c.halo}, 0.70),
          0 0 ${size === "lg" ? 32 : 22}px rgba(${c.halo}, 0.35),
          inset 0 0 2px rgba(0, 0, 0, 0.35)
        `,
        animation: `${c.anim} ${status === "error" ? "0.95s" : status === "warn" ? "1.8s" : "2.6s"} ease-in-out infinite`,
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Status word + color for the right-side badge
// ---------------------------------------------------------------------------

const STATUS_WORD: Record<Status, string> = { ok: "NOMINAL", warn: "DEGRADED", error: "OFFLINE" };
const STATUS_TEXT: Record<Status, string> = {
  ok:    "text-emerald-500",
  warn:  "text-amber-500",
  error: "text-red-500",
};

const OVERALL_COPY: Record<Overall, { status: Status; label: string }> = {
  healthy:  { status: "ok",    label: "All systems nominal" },
  degraded: { status: "warn",  label: "Running with issues" },
  critical: { status: "error", label: "Action required" },
};

// ---------------------------------------------------------------------------
// Time-ago ticker
// ---------------------------------------------------------------------------

function useTimeAgo(stamp: number | null) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!stamp) return "—";
  const sec = Math.max(0, Math.floor((now - stamp) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function WorkspaceHealthCard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stamp, setStamp] = useState<number | null>(null);
  const mountedRef = useRef(false);

  const load = useCallback(() => {
    if (mountedRef.current) setRefreshing(true); else setLoading(true);
    setError(null);
    fetch(`${API_BASE}/health/workspace`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((h: Health) => { setHealth(h); setStamp(Date.now()); })
      .catch((e) => setError(e.message))
      .finally(() => { setLoading(false); setRefreshing(false); mountedRef.current = true; });
  }, []);

  useEffect(() => { load(); }, [load]);

  const timeAgo = useTimeAgo(stamp);

  // ---- keyframes injected once ----
  const keyframes = `
    @keyframes led-ok    { 0%,100% { opacity: 1 } 50% { opacity: 0.55 } }
    @keyframes led-warn  { 0%,100% { opacity: 1 } 50% { opacity: 0.35 } }
    @keyframes led-error { 0%,100% { opacity: 1 } 45% { opacity: 0.2 } 55% { opacity: 1 } }
    @keyframes hc-row-in { from { opacity: 0; transform: translateY(4px) } to { opacity: 1; transform: none } }
    @keyframes hc-sweep  { 0% { transform: translateX(-100%) } 100% { transform: translateX(100%) } }
  `;

  // ---- Loading / error states ----

  if (loading && !health) {
    return (
      <div className="ios-card relative overflow-hidden">
        <style>{keyframes}</style>
        <div className="px-4 py-3.5 flex items-center gap-3">
          <span
            className="h-3 w-3 rounded-full bg-muted-foreground/30"
            style={{ animation: "led-warn 1.4s ease-in-out infinite" }}
          />
          <div>
            <p className="tracking-[0.22em] text-[10px] font-bold text-muted-foreground uppercase">System Status</p>
            <p className="text-sm text-muted-foreground">Running diagnostics…</p>
          </div>
        </div>
        {/* sweep shimmer */}
        <div
          className="absolute inset-0 pointer-events-none opacity-40"
          style={{
            background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent)",
            animation: "hc-sweep 1.6s ease-in-out infinite",
          }}
        />
      </div>
    );
  }

  if (error || !health) {
    return (
      <div className="ios-card px-4 py-3.5 flex items-center gap-3">
        <LED status="error" />
        <div className="flex-1">
          <p className="tracking-[0.22em] text-[10px] font-bold text-red-500 uppercase">System Status</p>
          <p className="text-sm text-muted-foreground">Could not reach diagnostics {error ? `— ${error}` : ""}</p>
        </div>
        <button onClick={load} className="text-xs text-primary hover:underline">Retry</button>
      </div>
    );
  }

  const overall = OVERALL_COPY[health.overall];

  return (
    <div className="ios-card overflow-hidden relative">
      <style>{keyframes}</style>

      {/* ── Header row ─────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 px-4 py-3.5 border-b border-[hsl(var(--ios-separator))]">
        <div className="flex items-center gap-3 min-w-0">
          <LED status={overall.status} size="lg" />
          <div className="min-w-0">
            <p className="tracking-[0.22em] text-[10px] font-bold text-muted-foreground uppercase leading-tight">
              System Status
            </p>
            <p className={cn("text-[15px] font-bold tracking-tight leading-tight", STATUS_TEXT[overall.status])}>
              {overall.label}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <span
            className="font-mono text-[10px] tracking-widest text-muted-foreground/70 tabular-nums hidden sm:inline"
            title={stamp ? new Date(stamp).toLocaleTimeString() : ""}
          >
            {timeAgo.toUpperCase()}
          </span>
          <button
            onClick={load}
            disabled={refreshing}
            aria-label="Re-check"
            className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* ── Check rows ─────────────────────────────────────────── */}
      <ul className="divide-y divide-[hsl(var(--ios-separator))]">
        {health.checks.map((c, i) => (
          <li
            key={c.id}
            className="group relative px-4 py-3 transition-colors hover:bg-secondary/30"
            style={{ animation: `hc-row-in 0.45s ${i * 60}ms ease-out backwards` }}
          >
            <div className="flex items-start gap-3">
              {/* LED rail */}
              <div className="pt-1 flex flex-col items-center">
                <LED status={c.status} />
              </div>

              {/* Body */}
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[12px] font-bold text-foreground tracking-[0.14em] uppercase leading-tight">
                    {c.label}
                  </p>
                  <span
                    className={cn(
                      "font-mono text-[9.5px] tracking-[0.2em] leading-tight shrink-0",
                      STATUS_TEXT[c.status]
                    )}
                  >
                    {STATUS_WORD[c.status]}
                  </span>
                </div>
                <p className="text-[12px] text-muted-foreground mt-0.5 leading-snug">{c.detail}</p>
                {c.action && c.status !== "ok" && (
                  <p className="text-[11px] text-muted-foreground/80 mt-1 flex items-center gap-1.5">
                    <span className={cn("font-bold", STATUS_TEXT[c.status])}>▸</span>
                    <span className="italic">{c.action}</span>
                  </p>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>

      {/* Subtle vignette at the bottom for depth */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-8"
        style={{
          background: "linear-gradient(to top, hsl(var(--card)) 0%, transparent 100%)",
          opacity: 0.0,
        }}
      />
    </div>
  );
}
