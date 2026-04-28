import { useEffect, useState } from "react";
import { Check, X, Loader2 } from "lucide-react";
import { getToken } from "../../api/auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

async function api(path: string) {
  const r = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  return r.ok ? r.json() : null;
}

interface Props { onFinish: () => void; onBack: () => void; completing: boolean }

export default function Step6Review({ onFinish, onBack, completing }: Props) {
  const [check, setCheck] = useState<{ label: string; ok: boolean }[] | null>(null);
  useEffect(() => {
    Promise.all([
      api("/settings/pipeline"),
      api("/settings/bot/status"),
      api("/settings/telethon/status"),
      api("/settings/meta/status"),
    ]).then(([pipe, bot, tg, meta]) => {
      setCheck([
        { label: `Pipeline configured (${pipe?.stages?.length ?? 0} stages)`, ok: !!pipe?.stages?.length },
        { label: "Bot connected",             ok: !!(bot?.has_token || bot?.connected) },
        { label: "Conversion desk connected", ok: !!(tg?.connected || tg?.is_connected) },
        { label: "Meta integration",          ok: !!(meta?.has_token || meta?.connected) },
      ]);
    });
  }, []);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Review &amp; launch</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Anything skipped can be configured from Settings later.
        </p>
      </div>
      {check ? (
        <ul className="rounded-lg border border-border divide-y divide-border bg-secondary/20">
          {check.map((c) => (
            <li key={c.label} className="flex items-center gap-3 px-3 py-2.5 text-sm">
              {c.ok ? <Check className="h-4 w-4 text-emerald-500" /> : <X className="h-4 w-4 text-muted-foreground" />}
              <span className={c.ok ? "text-foreground" : "text-muted-foreground"}>{c.label}</span>
            </li>
          ))}
        </ul>
      ) : (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      )}
      <div className="flex gap-2">
        <button onClick={onBack} className="px-3 h-10 rounded-lg border border-border text-sm hover:bg-secondary/40 transition-colors">
          Back
        </button>
        <button
          onClick={onFinish}
          disabled={completing}
          className="flex-1 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold transition-colors hover:bg-primary/90 disabled:opacity-50">
          {completing ? "Finishing…" : "Take me to my dashboard"}
        </button>
      </div>
    </div>
  );
}
