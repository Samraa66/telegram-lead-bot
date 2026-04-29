import { useEffect, useState } from "react";
import { ArrowUp, ArrowDown, Plus, Trash2, Star, CreditCard, X } from "lucide-react";
import {
  fetchPipeline, createStage, updateStage, deleteStage, reorderStages, updateFlags,
  PipelineConfig, PipelineStage,
} from "../../api/pipeline";
import { refreshPipeline } from "../../hooks/useWorkspaceStages";

export default function PipelineEditor() {
  const [cfg, setCfg] = useState<PipelineConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = () =>
    refreshPipeline().then(setCfg).catch((e: Error) => setError(e.message));
  useEffect(() => { reload(); }, []);

  if (!cfg) return <div className="text-sm text-muted-foreground">Loading…</div>;

  const wrap = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); await reload(); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const move = (id: number, dir: -1 | 1) => {
    const ids = cfg.stages.map((s) => s.id);
    const i = ids.indexOf(id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    return wrap(() => reorderStages(ids));
  };

  const renameStage = (s: PipelineStage, newName: string) => {
    if (!newName.trim() || newName === s.name) return;
    return wrap(() => updateStage(s.id, { name: newName.trim() }));
  };

  const removeStage = async (s: PipelineStage) => {
    setBusy(true); setError(null);
    try { await deleteStage(s.id); }
    catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      const target = window.prompt(`${msg}\nMove existing contacts to which stage id?`);
      if (target) {
        try { await deleteStage(s.id, Number(target)); }
        catch (e2: unknown) { setError(e2 instanceof Error ? e2.message : String(e2)); }
      }
    }
    await reload();
    setBusy(false);
  };

  const [markerInput, setMarkerInput] = useState("");

  const addMarker = () => {
    const raw = markerInput.trim().toLowerCase();
    if (!raw) return;
    if (cfg.vip_marker_phrases.includes(raw)) { setMarkerInput(""); return; }
    const next = [...cfg.vip_marker_phrases, raw];
    setMarkerInput("");
    return wrap(() => updateFlags({ vip_marker_phrases: next }));
  };

  const removeMarker = (m: string) => {
    const next = cfg.vip_marker_phrases.filter((x) => x !== m);
    return wrap(() => updateFlags({ vip_marker_phrases: next }));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Stages</h3>
          <p className="text-xs text-muted-foreground">
            Add, rename, reorder, or mark which stage means "deposited" or "member".
          </p>
        </div>
        <button onClick={() => wrap(() => createStage({ name: "New Stage", color: "#94a3b8" }))}
          disabled={busy}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-primary text-primary-foreground disabled:opacity-50">
          <Plus className="h-3.5 w-3.5" /> Add stage
        </button>
      </div>

      {error && <p className="text-[12px] text-destructive">{error}</p>}

      <div className="space-y-1.5">
        {cfg.stages.map((s, i) => (
          <div key={s.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-secondary/40 border border-border">
            <span className="font-mono text-[11px] text-muted-foreground w-6">{s.position}</span>
            <input
              defaultValue={s.name}
              onBlur={(e) => renameStage(s, e.target.value)}
              className="flex-1 bg-transparent text-sm text-foreground outline-none"
              placeholder="Stage name"
            />
            <button onClick={() => wrap(() => updateFlags({ deposited_stage_id: s.id }))}
              title="Mark as deposit stage"
              disabled={busy}
              className={`h-7 w-7 rounded grid place-items-center transition-colors ${
                cfg.deposited_stage_id === s.id ? "bg-emerald-500/15 text-emerald-500" :
                "text-muted-foreground hover:bg-secondary"}`}>
              <CreditCard className="h-3.5 w-3.5" />
            </button>
            <button onClick={() => wrap(() => updateFlags({ member_stage_id: s.id }))}
              title="Mark as member stage"
              disabled={busy}
              className={`h-7 w-7 rounded grid place-items-center transition-colors ${
                cfg.member_stage_id === s.id ? "bg-purple-500/15 text-purple-500" :
                "text-muted-foreground hover:bg-secondary"}`}>
              <Star className="h-3.5 w-3.5" />
            </button>
            <button onClick={() => move(s.id, -1)} disabled={i === 0 || busy}
              className="h-7 w-7 rounded text-muted-foreground hover:bg-secondary disabled:opacity-30">
              <ArrowUp className="h-3.5 w-3.5" />
            </button>
            <button onClick={() => move(s.id, 1)} disabled={i === cfg.stages.length - 1 || busy}
              className="h-7 w-7 rounded text-muted-foreground hover:bg-secondary disabled:opacity-30">
              <ArrowDown className="h-3.5 w-3.5" />
            </button>
            <button onClick={() => removeStage(s)} disabled={busy}
              className="h-7 w-7 rounded text-destructive hover:bg-destructive/10 disabled:opacity-30">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      <div className="pt-4 border-t border-border">
        <h3 className="text-sm font-semibold text-foreground">VIP name markers</h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          Names containing any of these as a standalone word auto-promote to the
          Member stage on first contact, on rename, and during Sync Telegram
          history. Case-insensitive. Defaults: <code className="font-mono">vip</code>, <code className="font-mono">premium</code>.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {cfg.vip_marker_phrases.map((m) => (
            <span
              key={m}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs bg-purple-500/15 text-purple-700 border border-purple-500/30"
            >
              <span className="font-mono">{m}</span>
              <button
                type="button"
                onClick={() => removeMarker(m)}
                disabled={busy}
                className="hover:bg-purple-500/20 rounded p-0.5 disabled:opacity-30"
                title={`Remove "${m}"`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <input
            value={markerInput}
            onChange={(e) => setMarkerInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addMarker(); } }}
            placeholder="Add marker… (Enter)"
            disabled={busy}
            className="flex-1 min-w-[140px] text-xs bg-transparent border border-border rounded-md px-2 py-1 outline-none focus:border-primary disabled:opacity-50"
          />
        </div>
      </div>
    </div>
  );
}
