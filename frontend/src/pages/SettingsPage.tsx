import { useEffect, useRef, useState } from "react";
import { ChevronDown, ExternalLink, Copy, Check } from "lucide-react";
import AppLayout from "@/components/AppLayout";
import {
  Keyword, FollowUpTemplate, QuickReply, TeamMember,
  fetchKeywords, createKeyword, updateKeyword, deleteKeyword,
  fetchFollowUpTemplates, updateFollowUp,
  fetchQuickReplies, createQuickReply, updateQuickReply, deleteQuickReply,
  fetchTeam, createTeamMember, updateTeamMember, resetTeamPassword, deleteTeamMember,
} from "../api/settings";
import { useWorkspaceStages } from "../hooks/useWorkspaceStages";
import PipelineEditor from "../components/pipeline/PipelineEditor";
import { cn } from "../lib/utils";

// ---- helpers ----

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

function authHeaders() {
  const token = localStorage.getItem("crm_token");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

// ---- sub-components ----

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
    </div>
  );
}

function SaveButton({ saving, onClick }: { saving: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={saving}
      className="px-3 py-1 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
    >
      {saving ? "Saving…" : "Save"}
    </button>
  );
}

function DeleteButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="px-2 py-1 text-xs rounded-md text-destructive hover:bg-destructive/10 transition-colors"
    >
      Remove
    </button>
  );
}

// ---- Setup Guide ----

function SetupGuide({ steps, defaultOpen = true }: {
  steps: React.ReactNode[];
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-primary/20 bg-primary/5">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left gap-2"
      >
        <span className="text-xs font-semibold text-primary">Setup guide</span>
        <ChevronDown className={cn("w-3.5 h-3.5 text-primary transition-transform shrink-0", open && "rotate-180")} />
      </button>
      {open && (
        <ol className="px-4 pb-4 space-y-2.5">
          {steps.map((step, i) => (
            <li key={i} className="flex gap-3 text-sm">
              <span className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/20 text-primary text-xs font-semibold flex items-center justify-center mt-0.5">
                {i + 1}
              </span>
              <span className="leading-relaxed text-foreground/80">{step}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---- Keywords tab ----

function KeywordsTab() {
  const pipeline = useWorkspaceStages();
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [loading, setLoading] = useState(true);
  const [newKw, setNewKw] = useState("");
  const [newStageId, setNewStageId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);
  const [editText, setEditText] = useState<Record<number, string>>({});

  const stages = pipeline?.stages || [];

  useEffect(() => {
    fetchKeywords()
      .then(setKeywords)
      .finally(() => setLoading(false));
  }, []);

  // Set default newStageId once stages load
  useEffect(() => {
    if (stages.length > 0 && newStageId === null) {
      setNewStageId(stages[0].id);
    }
  }, [stages, newStageId]);

  async function handleAdd() {
    if (!newKw.trim() || newStageId === null) return;
    setAdding(true);
    try {
      const created = await createKeyword(newKw.trim(), newStageId);
      setKeywords(prev => [...prev, created]);
      setNewKw("");
    } finally {
      setAdding(false);
    }
  }

  async function handleSave(kw: Keyword) {
    setSaving(kw.id);
    try {
      const updated = await updateKeyword(kw.id, { keyword: editText[kw.id] ?? kw.keyword });
      setKeywords(prev => prev.map(k => k.id === kw.id ? updated : k));
      setEditText(prev => { const n = { ...prev }; delete n[kw.id]; return n; });
    } finally {
      setSaving(null);
    }
  }

  async function handleToggle(kw: Keyword) {
    const updated = await updateKeyword(kw.id, { is_active: !kw.is_active });
    setKeywords(prev => prev.map(k => k.id === kw.id ? updated : k));
  }

  async function handleDelete(id: number) {
    await deleteKeyword(id);
    setKeywords(prev => prev.filter(k => k.id !== id));
  }

  // Find stage name for a keyword's target_stage_id
  function stageName(kw: Keyword): string {
    const id = kw.target_stage_id ?? kw.target_stage;
    const s = stages.find(st => st.id === id);
    return s ? s.name : `Stage ${id}`;
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div>
      <SectionHeader
        title="Stage Keywords"
        description="When an outgoing message contains this phrase, the lead automatically advances to that stage."
      />

      <div className="space-y-2 mb-6">
        {keywords.map(kw => {
          const text = editText[kw.id] ?? kw.keyword;
          const dirty = editText[kw.id] !== undefined && editText[kw.id] !== kw.keyword;
          return (
            <div key={kw.id} className={cn("flex items-center gap-3 px-3 py-2 rounded-lg border bg-card", !kw.is_active && "opacity-50")}>
              <span className="shrink-0 text-xs font-semibold text-muted-foreground whitespace-nowrap">{stageName(kw)}</span>
              <input
                className="flex-1 text-sm bg-transparent border-none outline-none focus:ring-0"
                value={text}
                onChange={e => setEditText(prev => ({ ...prev, [kw.id]: e.target.value }))}
              />
              {dirty && <SaveButton saving={saving === kw.id} onClick={() => handleSave(kw)} />}
              <button
                onClick={() => handleToggle(kw)}
                className={cn("text-xs px-2 py-1 rounded-md transition-colors", kw.is_active ? "text-muted-foreground hover:bg-muted" : "text-primary hover:bg-primary/10")}
              >
                {kw.is_active ? "Disable" : "Enable"}
              </button>
              <DeleteButton onClick={() => handleDelete(kw.id)} />
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2 p-3 rounded-lg border border-dashed bg-muted/30">
        <select
          value={newStageId ?? ""}
          onChange={e => setNewStageId(Number(e.target.value))}
          className="text-sm border rounded-md px-2 py-1.5 bg-background shrink-0"
        >
          {stages.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <input
          className="flex-1 text-sm border rounded-md px-3 py-1.5 bg-background"
          placeholder="Enter keyword phrase…"
          value={newKw}
          onChange={e => setNewKw(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleAdd()}
        />
        <button
          onClick={handleAdd}
          disabled={adding || !newKw.trim() || newStageId === null}
          className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors shrink-0"
        >
          {adding ? "Adding…" : "Add"}
        </button>
      </div>
    </div>
  );
}

// ---- Follow-up Templates tab ----

function FollowUpsTab() {
  const pipeline = useWorkspaceStages();
  const [templates, setTemplates] = useState<FollowUpTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [editText, setEditText] = useState<Record<number, string>>({});
  const [editHours, setEditHours] = useState<Record<number, number>>({});
  const [saving, setSaving] = useState<number | null>(null);

  const stages = pipeline?.stages || [];

  useEffect(() => {
    fetchFollowUpTemplates()
      .then(setTemplates)
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(tmpl: FollowUpTemplate) {
    setSaving(tmpl.id);
    try {
      const body: { message_text?: string; hours_offset?: number } = {};
      if (editText[tmpl.id] !== undefined) body.message_text = editText[tmpl.id];
      if (editHours[tmpl.id] !== undefined) body.hours_offset = editHours[tmpl.id];
      const updated = await updateFollowUp(tmpl.id, body);
      setTemplates(prev => prev.map(t => t.id === tmpl.id ? updated : t));
      setEditText(prev => { const n = { ...prev }; delete n[tmpl.id]; return n; });
      setEditHours(prev => { const n = { ...prev }; delete n[tmpl.id]; return n; });
    } finally {
      setSaving(null);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  // Group by stage_id if available, else by legacy stage number
  const grouped = new Map<string, FollowUpTemplate[]>();
  for (const tmpl of templates) {
    const key = tmpl.stage_id != null ? `id:${tmpl.stage_id}` : `num:${tmpl.stage}`;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(tmpl);
  }

  function groupLabel(key: string): string {
    if (key.startsWith("id:")) {
      const id = Number(key.slice(3));
      const s = stages.find(st => st.id === id);
      return s ? s.name : `Stage ${id}`;
    }
    return `Stage ${key.slice(4)}`;
  }

  return (
    <div>
      <SectionHeader
        title="Follow-up Templates"
        description="Automated messages sent when a lead has not responded. One per stage sequence slot."
      />
      <div className="space-y-6">
        {Array.from(grouped.entries()).map(([key, rows]) => (
          <div key={key}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{groupLabel(key)}</span>
            </div>
            <div className="space-y-2 pl-4">
              {rows.map(tmpl => {
                const text = editText[tmpl.id] ?? tmpl.message_text;
                const hours = editHours[tmpl.id] ?? tmpl.hours_offset;
                const dirty = (editText[tmpl.id] !== undefined && editText[tmpl.id] !== tmpl.message_text)
                  || (editHours[tmpl.id] !== undefined && editHours[tmpl.id] !== tmpl.hours_offset);
                return (
                  <div key={tmpl.id} className="rounded-lg border bg-card p-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-muted-foreground">Follow-up #{tmpl.sequence_num}</span>
                        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          Delay:
                          <input
                            type="number"
                            min={0}
                            className="w-16 text-xs border rounded px-1.5 py-0.5 bg-background"
                            value={hours}
                            onChange={e => setEditHours(prev => ({ ...prev, [tmpl.id]: Number(e.target.value) }))}
                          />
                          hours
                        </label>
                      </div>
                      {dirty && <SaveButton saving={saving === tmpl.id} onClick={() => handleSave(tmpl)} />}
                    </div>
                    <textarea
                      className="w-full text-sm bg-transparent border-none outline-none resize-none"
                      rows={2}
                      value={text}
                      onChange={e => setEditText(prev => ({ ...prev, [tmpl.id]: e.target.value }))}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- Quick Replies tab ----

function QuickRepliesTab() {
  const pipeline = useWorkspaceStages();
  const [replies, setReplies] = useState<QuickReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<number | null>(null);
  const [editData, setEditData] = useState<Record<number, Partial<QuickReply>>>({});
  const [adding, setAdding] = useState(false);
  const [newForm, setNewForm] = useState<{ stage_id: number | null; label: string; text: string }>({
    stage_id: null, label: "", text: "",
  });

  const stages = pipeline?.stages || [];

  useEffect(() => {
    fetchQuickReplies()
      .then(setReplies)
      .finally(() => setLoading(false));
  }, []);

  // Set default stage_id once stages load
  useEffect(() => {
    if (stages.length > 0 && newForm.stage_id === null) {
      setNewForm(f => ({ ...f, stage_id: stages[0].id }));
    }
  }, [stages, newForm.stage_id]);

  function patch(id: number, field: keyof QuickReply, value: string) {
    setEditData(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }));
  }

  async function handleSave(qr: QuickReply) {
    setSaving(qr.id);
    try {
      const updated = await updateQuickReply(qr.id, editData[qr.id] ?? {});
      setReplies(prev => prev.map(r => r.id === qr.id ? updated : r));
      setEditData(prev => { const n = { ...prev }; delete n[qr.id]; return n; });
    } finally {
      setSaving(null);
    }
  }

  async function handleToggle(qr: QuickReply) {
    const updated = await updateQuickReply(qr.id, { is_active: !qr.is_active });
    setReplies(prev => prev.map(r => r.id === qr.id ? updated : r));
  }

  async function handleDelete(id: number) {
    await deleteQuickReply(id);
    setReplies(prev => prev.filter(r => r.id !== id));
  }

  async function handleAdd() {
    if (!newForm.label.trim() || !newForm.text.trim() || newForm.stage_id === null) return;
    setAdding(true);
    try {
      const created = await createQuickReply(newForm.stage_id, newForm.label, newForm.text, 0);
      setReplies(prev => [...prev, created]);
      setNewForm(f => ({ ...f, label: "", text: "" }));
    } finally {
      setAdding(false);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  // Group by stage_id, with fallback to stage_num
  const grouped = new Map<number, QuickReply[]>();
  for (const qr of replies) {
    const key = qr.stage_id ?? qr.stage_num;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(qr);
  }

  function stageLabel(stageId: number): string {
    const s = stages.find(st => st.id === stageId);
    return s ? s.name : `Stage ${stageId}`;
  }

  return (
    <div>
      <SectionHeader
        title="Quick Replies"
        description="Pre-written message buttons shown in the CRM lead drawer, grouped by pipeline stage."
      />
      <div className="space-y-6 mb-8">
        {Array.from(grouped.entries()).map(([stageId, rows]) => (
          <div key={stageId}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{stageLabel(stageId)}</span>
            </div>
            <div className="space-y-2 pl-4">
              {rows.map(qr => {
                const ed = editData[qr.id] ?? {};
                const label = (ed.label as string | undefined) ?? qr.label;
                const text = (ed.text as string | undefined) ?? qr.text;
                const dirty = Object.keys(ed).length > 0;
                return (
                  <div key={qr.id} className={cn("rounded-lg border bg-card p-3", !qr.is_active && "opacity-50")}>
                    <div className="flex items-center gap-2 mb-2">
                      <input
                        className="text-xs font-medium border rounded px-2 py-1 bg-background w-32"
                        value={label}
                        onChange={e => patch(qr.id, "label", e.target.value)}
                        placeholder="Button label"
                      />
                      <div className="flex items-center gap-1 ml-auto">
                        {dirty && <SaveButton saving={saving === qr.id} onClick={() => handleSave(qr)} />}
                        <button
                          onClick={() => handleToggle(qr)}
                          className="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted transition-colors"
                        >
                          {qr.is_active ? "Disable" : "Enable"}
                        </button>
                        <DeleteButton onClick={() => handleDelete(qr.id)} />
                      </div>
                    </div>
                    <textarea
                      className="w-full text-sm bg-transparent border-none outline-none resize-none"
                      rows={2}
                      value={text}
                      onChange={e => patch(qr.id, "text", e.target.value)}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-dashed bg-muted/30 p-4">
        <p className="text-xs font-medium text-muted-foreground mb-3">Add new quick reply</p>
        <div className="flex items-center gap-2 mb-2">
          <select
            value={newForm.stage_id ?? ""}
            onChange={e => setNewForm(f => ({ ...f, stage_id: Number(e.target.value) }))}
            className="text-sm border rounded-md px-2 py-1.5 bg-background"
          >
            {stages.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <input
            className="flex-1 text-sm border rounded-md px-3 py-1.5 bg-background"
            placeholder="Button label (e.g. Qualify)"
            value={newForm.label}
            onChange={e => setNewForm(f => ({ ...f, label: e.target.value }))}
          />
        </div>
        <textarea
          className="w-full text-sm border rounded-md px-3 py-2 bg-background mb-2 resize-none"
          rows={2}
          placeholder="Message text…"
          value={newForm.text}
          onChange={e => setNewForm(f => ({ ...f, text: e.target.value }))}
        />
        <button
          onClick={handleAdd}
          disabled={adding || !newForm.label.trim() || !newForm.text.trim() || newForm.stage_id === null}
          className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {adding ? "Adding…" : "Add Quick Reply"}
        </button>
      </div>
    </div>
  );
}


// ---- Team tab ----

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  operator: "Operator",
  vip_manager: "VIP Manager",
};

const ROLE_COLORS: Record<string, string> = {
  admin: "bg-purple-100 text-purple-700",
  operator: "bg-blue-100 text-blue-700",
  vip_manager: "bg-emerald-100 text-emerald-700",
};

function CredentialBanner({ username, password, onDismiss }: { username: string; password: string; onDismiss: () => void }) {
  return (
    <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="text-xs font-semibold text-amber-800 mb-2">Save these credentials — the password won't be shown again</p>
      <div className="flex items-center gap-4 text-sm font-mono text-amber-900">
        <span><span className="text-amber-600 font-sans text-xs">Username:</span> {username}</span>
        <span><span className="text-amber-600 font-sans text-xs">Password:</span> {password}</span>
      </div>
      <button onClick={onDismiss} className="mt-2 text-xs text-amber-600 hover:underline">Dismiss</button>
    </div>
  );
}

function TeamTab() {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [newCreds, setNewCreds] = useState<{ username: string; password: string } | null>(null);
  const [resetCreds, setResetCreds] = useState<{ username: string; password: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ display_name: "", username: "", role: "operator" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTeam()
      .then(setMembers)
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (!form.display_name.trim() || !form.username.trim()) return;
    setAdding(true);
    setError(null);
    try {
      const created = await createTeamMember(form.display_name, form.username, form.role, "telegram");
      setMembers(prev => [...prev, created]);
      setForm({ display_name: "", username: "", role: "operator" });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create member");
    } finally {
      setAdding(false);
    }
  }

  async function handleToggleActive(m: TeamMember) {
    const updated = await updateTeamMember(m.id, { is_active: !m.is_active });
    setMembers(prev => prev.map(r => r.id === m.id ? updated : r));
  }

  async function handleResetPassword(m: TeamMember) {
    const res = await resetTeamPassword(m.id);
    setResetCreds({ username: m.username, password: res.password });
  }

  async function handleDelete(id: number) {
    await deleteTeamMember(id);
    setMembers(prev => prev.filter(m => m.id !== id));
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div>
      <SectionHeader
        title="Team Members"
        description="Add team members by their Telegram username. They sign in using the Telegram button on the login page."
      />

      {newCreds && (
        <CredentialBanner
          username={newCreds.username}
          password={newCreds.password}
          onDismiss={() => setNewCreds(null)}
        />
      )}
      {resetCreds && (
        <CredentialBanner
          username={resetCreds.username}
          password={resetCreds.password}
          onDismiss={() => setResetCreds(null)}
        />
      )}

      <div className="space-y-2 mb-6">
        {members.length === 0 && (
          <p className="text-sm text-muted-foreground py-4 text-center">No team members yet.</p>
        )}
        {members.map(m => (
          <div key={m.id} className={cn("flex items-center gap-3 px-4 py-3 rounded-lg border bg-card", !m.is_active && "opacity-50")}>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium truncate">{m.display_name}</span>
                <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", ROLE_COLORS[m.role] ?? "bg-gray-100 text-gray-600")}>
                  {ROLE_LABELS[m.role] ?? m.role}
                </span>
                {m.auth_type === "telegram" && (
                  <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-sky-100 text-sky-700">Telegram</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">@{m.username}</p>
            </div>
            {m.auth_type === "password" && (
              <button
                onClick={() => handleResetPassword(m)}
                className="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted transition-colors shrink-0"
              >
                Reset password
              </button>
            )}
            <button
              onClick={() => handleToggleActive(m)}
              className="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted transition-colors shrink-0"
            >
              {m.is_active ? "Deactivate" : "Activate"}
            </button>
            <DeleteButton onClick={() => handleDelete(m.id)} />
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-dashed bg-muted/30 p-4">
        <p className="text-xs font-medium text-muted-foreground mb-3">Add team member</p>
        <div className="flex items-center gap-2 mb-2">
          <input
            className="flex-1 text-sm border rounded-md px-3 py-1.5 bg-background"
            placeholder="Display name (e.g. Talal)"
            value={form.display_name}
            onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))}
          />
          <input
            className="flex-1 text-sm border rounded-md px-3 py-1.5 bg-background"
            placeholder="Telegram @username (without @)"
            value={form.username}
            onChange={e => setForm(f => ({ ...f, username: e.target.value.toLowerCase().replace(/[@\s]/g, "") }))}
          />
          <select
            value={form.role}
            onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
            className="text-sm border rounded-md px-2 py-1.5 bg-background shrink-0"
          >
            <option value="operator">Operator</option>
            <option value="vip_manager">VIP Manager</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        {error && <p className="text-xs text-destructive mb-2">{error}</p>}
        <button
          onClick={handleCreate}
          disabled={adding || !form.display_name.trim() || !form.username.trim()}
          className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {adding ? "Creating…" : "Add Member"}
        </button>
      </div>
    </div>
  );
}

// ---- Telegram Bot tab ----

function BotTab() {
  const [status, setStatus] = useState<{
    has_token: boolean;
    webhook_url: string | null;
    webhook_active: boolean;
    webhook_correct: boolean | null;
    expected_url: string | null;
  } | null>(null);
  const [form, setForm] = useState({ bot_token: "", webhook_secret: "" });
  const [saving, setSaving] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function refreshStatus() {
    const s = await fetch(`${API_BASE}/settings/bot/status`, { headers: authHeaders() })
      .then(r => r.json())
      .catch(() => null);
    if (s) setStatus(s);
  }

  useEffect(() => { refreshStatus(); }, []);

  async function handleSave() {
    if (!form.bot_token.trim()) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const body: Record<string, string> = { bot_token: form.bot_token.trim() };
      if (form.webhook_secret.trim()) body.webhook_secret = form.webhook_secret.trim();
      const res = await fetch(`${API_BASE}/settings/bot/credentials`, {
        method: "PATCH",
        headers: authHeaders(),
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to save");
      setSuccess("Bot token saved.");
      setForm({ bot_token: "", webhook_secret: "" });
      await refreshStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setSaving(false);
    }
  }

  async function handleRegisterWebhook() {
    setRegistering(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await fetch(`${API_BASE}/settings/bot/register-webhook`, {
        method: "POST",
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to register webhook");
      setSuccess("Webhook registered — bot is live.");
      await refreshStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setRegistering(false);
    }
  }

  const webhookOk = status?.webhook_correct === true;
  const webhookWrong = status?.webhook_active && status?.webhook_correct === false;

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Acquisition Bot"
        description="Captures every lead from your ads. Create a bot via BotFather, paste the token here, and register the webhook so Telegram forwards incoming DMs to your CRM."
      />

      <SetupGuide
        defaultOpen={!webhookOk}
        steps={[
          <>Open Telegram and search <code className="font-mono bg-muted px-1 rounded text-xs">@BotFather</code>, then tap <strong>Start</strong>.</>,
          <>Send <code className="font-mono bg-muted px-1 rounded text-xs">/newbot</code> and follow the prompts — choose a display name, then a username ending in <code className="font-mono bg-muted px-1 rounded text-xs">_bot</code>.</>,
          <>BotFather will reply with your token — a string like <code className="font-mono bg-muted px-1 rounded text-xs">123456789:ABCDef-ghijklmnop</code>. Copy it.</>,
          <>Paste it in the <strong>Bot Token</strong> field below and click <strong>Save Token</strong>.</>,
          <>Click <strong>Register Webhook</strong> — this points Telegram to your CRM so incoming messages are forwarded automatically.</>,
        ]}
      />

      {/* Status card */}
      {status && (
        <div className={cn(
          "rounded-lg border p-4 flex items-start gap-3",
          webhookOk   ? "bg-green-50 border-green-200" :
          webhookWrong ? "bg-amber-50 border-amber-200" :
          "bg-muted/30 border-border"
        )}>
          <div className={cn(
            "w-2 h-2 rounded-full shrink-0 mt-1.5",
            webhookOk    ? "bg-green-500" :
            webhookWrong ? "bg-amber-400" : "bg-gray-400"
          )} />
          <div className="flex-1 min-w-0">
            {!status.has_token ? (
              <p className="text-sm font-medium text-muted-foreground">No bot token saved yet</p>
            ) : webhookOk ? (
              <>
                <p className="text-sm font-medium text-green-800">Bot connected and active</p>
                <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">{status.webhook_url}</p>
              </>
            ) : webhookWrong ? (
              <>
                <p className="text-sm font-medium text-amber-800">Webhook pointing to wrong URL</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Current: <span className="font-mono">{status.webhook_url}</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  Expected: <span className="font-mono">{status.expected_url}</span>
                </p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium">Token saved — webhook not yet registered</p>
                <p className="text-xs text-muted-foreground mt-0.5">Register the webhook below to activate the bot.</p>
              </>
            )}
          </div>
          {status.has_token && !webhookOk && (
            <button
              onClick={handleRegisterWebhook}
              disabled={registering}
              className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors shrink-0"
            >
              {registering ? "Registering…" : "Register Webhook"}
            </button>
          )}
        </div>
      )}

      {/* Form */}
      <div className="rounded-lg border border-dashed bg-muted/30 p-4 space-y-3">
        <p className="text-xs font-medium text-muted-foreground">
          {status?.has_token ? "Update bot token" : "Enter your bot token"}
        </p>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Bot Token</label>
          <input
            type="password"
            className="w-full text-sm border rounded-md px-3 py-1.5 bg-background font-mono"
            placeholder="123456789:ABCDef-ghijklmnop"
            value={form.bot_token}
            onChange={e => setForm(f => ({ ...f, bot_token: e.target.value }))}
            onKeyDown={e => e.key === "Enter" && handleSave()}
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">
            Webhook Secret <span className="text-muted-foreground/50 font-normal">(optional)</span>
          </label>
          <input
            className="w-full text-sm border rounded-md px-3 py-1.5 bg-background font-mono"
            placeholder="Any random string — adds a security check on incoming updates"
            value={form.webhook_secret}
            onChange={e => setForm(f => ({ ...f, webhook_secret: e.target.value }))}
          />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        {success && <p className="text-xs text-green-600">{success}</p>}
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving || !form.bot_token.trim()}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving…" : "Save Token"}
          </button>
          {webhookOk && (
            <button
              onClick={handleRegisterWebhook}
              disabled={registering}
              className="px-3 py-1.5 text-sm rounded-md border hover:bg-muted transition-colors disabled:opacity-50 text-sm"
            >
              {registering ? "Registering…" : "Re-register Webhook"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Conversion Desk (Telethon) tab ----

type TelethonStep = "idle" | "phone" | "otp" | "connected";

type ForwardingStatus = {
  bot_configured: boolean;
  source_configured: boolean;
  destination_count: number;
  active: boolean;
} | null;

function ForwardingStatusCard() {
  const [status, setStatus] = useState<ForwardingStatus>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/settings/forwarding/status`, { headers: authHeaders() })
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => setStatus(d))
      .catch(() => setFailed(true));
  }, []);

  if (failed) return null;
  if (!status) return (
    <div className="rounded-lg border p-4 flex items-center gap-2 text-xs text-muted-foreground">
      <span className="h-2 w-2 rounded-full bg-muted-foreground/30 animate-pulse shrink-0" />
      Checking forwarding status…
    </div>
  );

  const checks = [
    { label: "Bot token",            ok: status.bot_configured    },
    { label: "Source channel",       ok: status.source_configured },
    { label: "Destination channels", ok: status.destination_count > 0,
      detail: status.destination_count > 0 ? `${status.destination_count} channel${status.destination_count !== 1 ? "s" : ""}` : "none configured" },
  ];

  return (
    <div className={cn(
      "rounded-lg border p-4 space-y-3",
      status.active ? "bg-green-500/10 border-green-500/30" : "bg-amber-500/10 border-amber-500/30"
    )}>
      <div className="flex items-center gap-2">
        <span className={cn(
          "h-2.5 w-2.5 rounded-full shrink-0",
          status.active ? "bg-green-500 animate-pulse" : "bg-amber-500"
        )} />
        <p className={cn(
          "text-sm font-semibold",
          status.active ? "text-green-500" : "text-amber-500"
        )}>
          Signal forwarding {status.active ? "active" : "inactive"}
        </p>
      </div>
      <div className="space-y-1.5">
        {checks.map(({ label, ok, detail }) => (
          <div key={label} className="flex items-center gap-2 text-xs">
            <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", ok ? "bg-green-500" : "bg-muted-foreground/40")} />
            <span className={cn(ok ? "text-foreground" : "text-muted-foreground")}>{label}</span>
            {detail && <span className="text-muted-foreground">— {detail}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- Signal Forwarding tab ----

type ForwardingConfig = {
  source_channel_id: string | null;
  destination_channel_ids: string | null;
  effective_source_channel_id: string | null;
  effective_destinations: string[];
  affiliate_destinations: { id: number; name: string; vip_channel_id: string }[];
};

function SignalForwardingTab() {
  const [config, setConfig] = useState<ForwardingConfig | null>(null);
  const [form, setForm] = useState({ source: "", destinations: "" });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/settings/forwarding/config`, { headers: authHeaders() })
      .then(r => { if (!r.ok) throw new Error("Failed to load forwarding config"); return r.json(); })
      .then((c: ForwardingConfig) => {
        setConfig(c);
        setForm({
          source: c.source_channel_id || "",
          destinations: c.destination_channel_ids || "",
        });
      })
      .catch(e => setError(e.message));
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(`${API_BASE}/settings/forwarding/config`, {
        method: "PATCH",
        headers: authHeaders(),
        body: JSON.stringify({
          source_channel_id: form.source.trim(),
          destination_channel_ids: form.destinations.trim(),
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to save");
      setSaved(true);
      // Reload config
      const fresh = await fetch(`${API_BASE}/settings/forwarding/config`, { headers: authHeaders() }).then(r => r.json());
      setConfig(fresh);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (!config) {
    return (
      <div className="text-xs text-muted-foreground">{error || "Loading forwarding config…"}</div>
    );
  }

  return (
    <div className="space-y-6">
      <ForwardingStatusCard />

      {/* Source channel */}
      <div className="rounded-lg border p-4 space-y-3">
        <div>
          <h4 className="text-sm font-semibold">Source Channel</h4>
          <p className="text-xs text-muted-foreground mt-0.5">
            The channel your Conversion Desk listens to for trade signals. Every new post here gets copied to the destinations below.
          </p>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Channel ID</label>
          <input
            className="w-full text-sm border rounded-md px-3 py-1.5 bg-background font-mono"
            placeholder="-1001234567890"
            value={form.source}
            onChange={e => setForm(f => ({ ...f, source: e.target.value }))}
          />
          <p className="text-xs text-muted-foreground/70 mt-1">
            The channel ID starts with <code className="font-mono">-100</code>. Your Conversion Desk must be a member.
          </p>
        </div>
      </div>

      {/* Destination channels */}
      <div className="rounded-lg border p-4 space-y-3">
        <div>
          <h4 className="text-sm font-semibold">Destination Channels</h4>
          <p className="text-xs text-muted-foreground mt-0.5">
            Your own Signals channels that should receive every signal. Comma-separated. Affiliate Signals channels are added automatically (see below).
          </p>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Channel IDs (comma-separated)</label>
          <textarea
            className="w-full text-sm border rounded-md px-3 py-1.5 bg-background font-mono min-h-[60px]"
            placeholder="-1001234567890, -1009876543210"
            value={form.destinations}
            onChange={e => setForm(f => ({ ...f, destinations: e.target.value }))}
          />
        </div>

        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving…" : "Save Forwarding Config"}
          </button>
          {saved && <span className="text-xs text-green-600">Saved.</span>}
          {error && <span className="text-xs text-destructive">{error}</span>}
        </div>
      </div>

      {/* Affiliate destinations (read-only, auto-synced) */}
      <div className="rounded-lg border p-4 space-y-3">
        <div>
          <h4 className="text-sm font-semibold">Affiliate Signals Channels</h4>
          <p className="text-xs text-muted-foreground mt-0.5">
            Auto-synced from your affiliates' dashboards. Every active affiliate's linked Signals channel receives signals automatically — no action needed.
          </p>
        </div>
        {config.affiliate_destinations.length === 0 ? (
          <p className="text-xs text-muted-foreground">No affiliate Signals channels linked yet.</p>
        ) : (
          <div className="space-y-1.5">
            {config.affiliate_destinations.map(a => (
              <div key={a.id} className="flex items-center justify-between gap-2 text-xs">
                <span className="font-medium">{a.name}</span>
                <span className="font-mono text-muted-foreground">{a.vip_channel_id}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TelegramTab() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [step, setStep] = useState<TelethonStep>("idle");
  const [phone, setPhone] = useState("");
  const [phoneCodeHash, setPhoneCodeHash] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/settings/telethon/status`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => { setConnected(d.connected); setStep(d.connected ? "connected" : "idle"); })
      .catch(() => setConnected(false));
  }, []);

  async function handleSendCode() {
    if (!phone.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/telethon/connect`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ phone: phone.trim() }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to send code");
      const data = await res.json();
      setPhoneCodeHash(data.phone_code_hash);
      setStep("otp");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  }

  async function handleVerify() {
    if (!code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/telethon/verify`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ phone: phone.trim(), code: code.trim(), phone_code_hash: phoneCodeHash }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Verification failed");
      setConnected(true);
      setStep("connected");
      setPhone("");
      setCode("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    setError(null);
    try {
      await fetch(`${API_BASE}/settings/telethon/disconnect`, { method: "POST", headers: authHeaders() });
      setConnected(false);
      setStep("idle");
    } catch {
      setError("Failed to disconnect");
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Conversion Desk"
        description="Connects your personal Telegram account — the human who replies to leads and closes them. The CRM reads and sends on its behalf."
      />

      <SetupGuide
        defaultOpen={!connected}
        steps={[
          <>This links a <strong>personal Telegram account</strong> (not a bot) — the number your leads actually chat with once they're captured.</>,
          <>The CRM reads incoming messages from that account and auto-advances leads through the pipeline based on keywords.</>,
          <>Enter the phone number below in international format (e.g. <code className="font-mono bg-muted px-1 rounded text-xs">+971501234567</code>).</>,
          <>Telegram sends a <strong>5-digit code</strong> to that device — enter it to confirm.</>,
          <>The session is saved securely. You only do this once — it survives server restarts.</>,
          <span className="text-amber-700">Note: if the account has 2-step verification enabled, contact support — 2FA via UI is not yet supported.</span>,
        ]}
      />

      {connected === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : step === "connected" ? (
        <div className="rounded-lg border bg-green-50 border-green-200 p-4 flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-medium text-green-800">Operator account connected</p>
            <p className="text-xs text-muted-foreground mt-0.5">Messages sent from the dashboard go through this account.</p>
          </div>
          <button
            onClick={handleDisconnect}
            disabled={disconnecting}
            className="text-xs px-3 py-1.5 rounded-md text-red-600 hover:bg-destructive/10 border border-red-200 transition-colors shrink-0"
          >
            {disconnecting ? "Disconnecting…" : "Disconnect"}
          </button>
        </div>
      ) : step === "idle" || step === "phone" ? (
        <div className="rounded-lg border border-dashed bg-muted/30 p-4 space-y-3">
          <p className="text-xs font-medium text-muted-foreground">Enter the operator's phone number</p>
          <div className="flex gap-2">
            <input
              className="flex-1 text-sm border rounded-md px-3 py-1.5 bg-background"
              placeholder="+971 50 123 4567"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSendCode()}
            />
            <button
              onClick={handleSendCode}
              disabled={busy || !phone.trim()}
              className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors shrink-0"
            >
              {busy ? "Sending…" : "Send Code"}
            </button>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed bg-muted/30 p-4 space-y-3">
          <p className="text-xs font-medium text-muted-foreground">
            Enter the code Telegram sent to <span className="text-foreground font-mono">{phone}</span>
          </p>
          <div className="flex gap-2">
            <input
              className="flex-1 text-sm border rounded-md px-3 py-1.5 bg-background font-mono tracking-widest"
              placeholder="12345"
              value={code}
              onChange={e => setCode(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleVerify()}
              autoFocus
            />
            <button
              onClick={handleVerify}
              disabled={busy || !code.trim()}
              className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors shrink-0"
            >
              {busy ? "Verifying…" : "Verify"}
            </button>
          </div>
          <button
            onClick={() => { setStep("idle"); setError(null); setCode(""); }}
            className="text-xs text-muted-foreground hover:underline"
          >
            Use a different number
          </button>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      )}

    </div>
  );
}

// ---- Meta Integration tab ----

function MetaTab() {
  const [status, setStatus] = useState<{ connected: boolean; ad_account_id: string | null; pixel_id: string | null; landing_page_url: string | null } | null>(null);
  const [form, setForm] = useState({ access_token: "", ad_account_id: "", pixel_id: "", landing_page_url: "" });
  const [saving, setSaving] = useState(false);
  const [savingLanding, setSavingLanding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [landingSaved, setLandingSaved] = useState(false);
  const [snippetCopied, setSnippetCopied] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/settings/meta/status`, { headers: authHeaders() })
      .then(r => r.json())
      .then((s) => {
        setStatus(s);
        if (s?.landing_page_url) {
          setForm((f) => ({ ...f, landing_page_url: s.landing_page_url }));
        }
      })
      .catch(() => {});
  }, []);

  async function handleSave() {
    if (!form.access_token.trim() || !form.ad_account_id.trim() || !form.pixel_id.trim()) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/settings/meta/credentials`, {
        method: "PATCH",
        headers: authHeaders(),
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to save");
      setSuccess(true);
      setStatus({
        connected: true,
        ad_account_id: form.ad_account_id.trim(),
        pixel_id: form.pixel_id.trim(),
        landing_page_url: form.landing_page_url.trim() || null,
      });
      setForm((f) => ({ ...f, access_token: "", ad_account_id: "", pixel_id: "" }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveLanding() {
    setSavingLanding(true);
    setError(null);
    setLandingSaved(false);
    try {
      const res = await fetch(`${API_BASE}/settings/meta/credentials`, {
        method: "PATCH",
        headers: authHeaders(),
        body: JSON.stringify({ landing_page_url: form.landing_page_url.trim() }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to save");
      setLandingSaved(true);
      setStatus((s) => s ? { ...s, landing_page_url: form.landing_page_url.trim() || null } : s);
      setTimeout(() => setLandingSaved(false), 2500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setSavingLanding(false);
    }
  }

  const snippet = `<!-- Telelytics attribution: forwards ?src= from ad URL to Telegram bot /start param -->
<script>
(function(){
  var p = new URLSearchParams(window.location.search);
  var src = p.get('src') || p.get('utm_campaign') || p.get('utm_content');
  if (!src) return;
  try { localStorage.setItem('tl_src', src); } catch(e) {}
  document.querySelectorAll('a[href*="t.me/"]').forEach(function(a){
    try {
      var u = new URL(a.href);
      u.searchParams.set('start', src);
      a.href = u.toString();
    } catch(e) {}
  });
})();
</script>`;

  async function copySnippet() {
    try {
      await navigator.clipboard.writeText(snippet);
      setSnippetCopied(true);
      setTimeout(() => setSnippetCopied(false), 2000);
    } catch {}
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Meta Ads Integration"
        description="Connect your Meta ad account to pull campaign analytics and fire conversion events when leads deposit."
      />

      <SetupGuide
        defaultOpen={!status?.connected}
        steps={[
          // Access Token
          <>
            <span className="font-semibold text-foreground">Access Token —</span>{" "}
            Go to{" "}
            <a href="https://business.facebook.com" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">
              business.facebook.com <ExternalLink className="w-3 h-3" />
            </a>
            {" "}→ <strong>Settings</strong> → <strong>Users</strong> → <strong>System Users</strong>.
          </>,
          <>Create or select a System User, then click <strong>Generate New Token</strong>. Choose your app and enable these permissions: <code className="font-mono bg-muted px-1 rounded text-xs">ads_read</code>, <code className="font-mono bg-muted px-1 rounded text-xs">ads_management</code>, <code className="font-mono bg-muted px-1 rounded text-xs">business_management</code>. Copy the token — it is only shown once.</>,
          // Ad Account ID
          <>
            <span className="font-semibold text-foreground">Ad Account ID —</span>{" "}
            Open{" "}
            <a href="https://adsmanager.facebook.com" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">
              Ads Manager <ExternalLink className="w-3 h-3" />
            </a>. Your account ID appears at the top-left as <code className="font-mono bg-muted px-1 rounded text-xs">Act #1234567890</code>. Copy the number only — we add <code className="font-mono bg-muted px-1 rounded text-xs">act_</code> automatically.
          </>,
          // Pixel ID
          <>
            <span className="font-semibold text-foreground">Pixel ID —</span>{" "}
            Go to{" "}
            <a href="https://business.facebook.com/events_manager" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">
              Events Manager <ExternalLink className="w-3 h-3" />
            </a>
            {" "}→ <strong>Data Sources</strong> → select your pixel. The Pixel ID is the number shown at the top of the settings panel.
          </>,
        ]}
      />

      {/* Status */}
      {status && (
        <div className={cn(
          "rounded-lg border p-4 flex items-center gap-3",
          status.connected ? "bg-green-50 border-green-200" : "bg-muted/30"
        )}>
          <div className={cn("w-2 h-2 rounded-full shrink-0", status.connected ? "bg-green-500" : "bg-gray-400")} />
          <div>
            <p className="text-sm font-medium">{status.connected ? "Connected" : "Not connected"}</p>
            {status.connected && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {status.ad_account_id} · Pixel {status.pixel_id}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Form */}
      <div className="rounded-lg border border-dashed bg-muted/30 p-4 space-y-4">
        <p className="text-xs font-medium text-muted-foreground">
          {status?.connected ? "Update credentials" : "Enter your Meta credentials"}
        </p>

        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Access Token</label>
          <input
            type="password"
            className="w-full text-sm border rounded-md px-3 py-1.5 bg-background font-mono"
            placeholder="EAAxxxxxx…"
            value={form.access_token}
            onChange={e => setForm(f => ({ ...f, access_token: e.target.value }))}
          />
          <p className="text-xs text-muted-foreground/70 mt-1">
            System User token from Meta Business Suite → Settings → System Users
          </p>
        </div>

        <div className="flex gap-3">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">Ad Account ID</label>
            <input
              className="w-full text-sm border rounded-md px-3 py-1.5 bg-background"
              placeholder="123456789"
              value={form.ad_account_id}
              onChange={e => setForm(f => ({ ...f, ad_account_id: e.target.value }))}
            />
            <p className="text-xs text-muted-foreground/70 mt-1">
              Ads Manager top-left — number only, no <code className="font-mono text-xs">act_</code>
            </p>
          </div>
          <div className="flex-1">
            <label className="text-xs text-muted-foreground mb-1 block">Pixel ID</label>
            <input
              className="w-full text-sm border rounded-md px-3 py-1.5 bg-background"
              placeholder="123456789"
              value={form.pixel_id}
              onChange={e => setForm(f => ({ ...f, pixel_id: e.target.value }))}
            />
            <p className="text-xs text-muted-foreground/70 mt-1">
              Events Manager → Data Sources → your pixel
            </p>
          </div>
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}
        {success && <p className="text-xs text-green-600">Credentials saved successfully.</p>}
        <button
          onClick={handleSave}
          disabled={saving || !form.access_token.trim() || !form.ad_account_id.trim() || !form.pixel_id.trim()}
          className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving…" : "Save Credentials"}
        </button>
      </div>

      {/* Landing Page URL */}
      <div className="rounded-lg border p-4 space-y-3">
        <div>
          <h3 className="text-sm font-semibold">Landing Page URL</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            The public URL of your landing page. We'll use it to build per-campaign tracked links for your Meta ads.
          </p>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">URL</label>
          <input
            type="url"
            className="w-full text-sm border rounded-md px-3 py-1.5 bg-background font-mono"
            placeholder="https://your-landing.com"
            value={form.landing_page_url}
            onChange={e => setForm(f => ({ ...f, landing_page_url: e.target.value }))}
          />
          <p className="text-xs text-muted-foreground/70 mt-1">
            Example: <code className="font-mono text-xs">https://bullish-signals.com</code>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSaveLanding}
            disabled={savingLanding}
            className="px-3 py-1.5 text-sm rounded-md border hover:bg-muted transition-colors disabled:opacity-50"
          >
            {savingLanding ? "Saving…" : "Save URL"}
          </button>
          {landingSaved && <span className="text-xs text-green-600">Saved.</span>}
        </div>
      </div>

      {/* Attribution snippet */}
      <div className="rounded-lg border p-4 space-y-3">
        <div>
          <h3 className="text-sm font-semibold">Landing Page Attribution Snippet</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Paste this into the <code className="font-mono text-xs">&lt;head&gt;</code> of your landing page.
            It reads <code className="font-mono text-xs">?src=</code> from the URL and appends it to any Telegram bot link
            (<code className="font-mono text-xs">t.me/...</code>) on the page as the <code className="font-mono text-xs">/start</code> parameter
            so every lead is attributed to the campaign that sent them.
          </p>
        </div>
        <div className="relative">
          <pre className="text-[11px] bg-muted/50 rounded-md p-3 overflow-x-auto font-mono leading-relaxed border">
{snippet}
          </pre>
          <button
            onClick={copySnippet}
            className="absolute top-2 right-2 px-2 py-1 text-[11px] rounded-md bg-background border hover:bg-muted transition-colors flex items-center gap-1"
          >
            {snippetCopied ? <><Check className="h-3 w-3" /> Copied</> : <><Copy className="h-3 w-3" /> Copy</>}
          </button>
        </div>
        <div className="text-xs text-muted-foreground/80 space-y-1">
          <p className="font-semibold text-foreground">How the full flow works:</p>
          <ol className="list-decimal list-inside space-y-0.5 pl-1">
            <li>Generate a tracked campaign link in the Analytics page — this gives you a per-campaign landing URL (<code className="font-mono text-[10px]">...?src=cmp_xxx</code>).</li>
            <li>Use that landing URL as the destination URL in your Meta ad.</li>
            <li>User clicks ad → lands on your page → clicks the Telegram CTA.</li>
            <li>The snippet rewrites the CTA link to <code className="font-mono text-[10px]">t.me/YourBot?start=cmp_xxx</code> so the lead is auto-attributed.</li>
          </ol>
        </div>
      </div>
    </div>
  );
}

// ---- Main page ----

type Section = "pipeline" | "team" | "telegram" | "meta";
type PipelineTab = "stages" | "keywords" | "followups" | "quickreplies";

const SECTIONS: { id: Section; label: string }[] = [
  { id: "pipeline", label: "Pipeline"  },
  { id: "team",     label: "Team"      },
  { id: "telegram", label: "Telegram"  },
  { id: "meta",     label: "Meta Ads"  },
];

const PIPELINE_TABS: { id: PipelineTab; label: string }[] = [
  { id: "stages",       label: "Stages"       },
  { id: "keywords",     label: "Keywords"     },
  { id: "followups",    label: "Follow-ups"   },
  { id: "quickreplies", label: "Quick Replies" },
];

export default function SettingsPage() {
  const [section, setSection] = useState<Section>("pipeline");
  const [pipelineTab, setPipelineTab] = useState<PipelineTab>("stages");

  return (
    <AppLayout>
      <div className="flex h-full">
        {/* Left nav */}
        <aside className="w-48 shrink-0 border-r py-6 px-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-3 mb-2">Settings</p>
          <nav className="space-y-0.5">
            {SECTIONS.map(s => (
              <button
                key={s.id}
                onClick={() => setSection(s.id)}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-md text-sm transition-colors",
                  section === s.id
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted"
                )}
              >
                {s.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6 max-w-3xl">
          {section === "team" && (
            <>
              <h2 className="text-lg font-semibold mb-0.5">Team</h2>
              <p className="text-sm text-muted-foreground mb-6">Manage operator and manager accounts.</p>
              <TeamTab />
            </>
          )}

          {section === "pipeline" && (
            <>
              <h2 className="text-lg font-semibold mb-0.5">Pipeline</h2>
              <p className="text-sm text-muted-foreground mb-4">Configure how your CRM pipeline behaves.</p>

              <div className="flex gap-1 border-b mb-6">
                {PIPELINE_TABS.map(t => (
                  <button
                    key={t.id}
                    onClick={() => setPipelineTab(t.id)}
                    className={cn(
                      "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
                      pipelineTab === t.id
                        ? "border-primary text-primary"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {pipelineTab === "stages"       && <PipelineEditor />}
              {pipelineTab === "keywords"     && <KeywordsTab />}
              {pipelineTab === "followups"    && <FollowUpsTab />}
              {pipelineTab === "quickreplies" && <QuickRepliesTab />}
            </>
          )}

          {section === "telegram" && (
            <>
              <h2 className="text-lg font-semibold mb-0.5">Telegram</h2>
              <p className="text-sm text-muted-foreground mb-6">
                The three pieces that run your pipeline: the <strong>Acquisition Bot</strong> that captures leads, the <strong>Conversion Desk</strong> that closes them, and the <strong>Signal Forwarding</strong> that delivers trade signals to paid members.
              </p>

              {/* 1. Acquisition Bot */}
              <section className="mb-10">
                <div className="flex items-start gap-3 mb-4 pb-3 border-b">
                  <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-primary text-sm font-bold">1</span>
                  </div>
                  <div>
                    <h3 className="text-base font-semibold">Acquisition Bot</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Captures every lead who clicks your ads — the entry point of the funnel.
                    </p>
                  </div>
                </div>
                <BotTab />
              </section>

              {/* 2. Conversion Desk */}
              <section className="mb-10">
                <div className="flex items-start gap-3 mb-4 pb-3 border-b">
                  <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-primary text-sm font-bold">2</span>
                  </div>
                  <div>
                    <h3 className="text-base font-semibold">Conversion Desk</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Your personal Telegram account — the human on the other side who qualifies and closes leads.
                    </p>
                  </div>
                </div>
                <TelegramTab />
              </section>

              {/* 3. Signal Forwarding */}
              <section>
                <div className="flex items-start gap-3 mb-4 pb-3 border-b">
                  <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-primary text-sm font-bold">3</span>
                  </div>
                  <div>
                    <h3 className="text-base font-semibold">Signal Forwarding</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Mirrors trade signals from your source channel to every linked Signals channel automatically.
                    </p>
                  </div>
                </div>
                <SignalForwardingTab />
              </section>
            </>
          )}

          {section === "meta" && (
            <>
              <h2 className="text-lg font-semibold mb-0.5">Meta Ads</h2>
              <p className="text-sm text-muted-foreground mb-6">Connect your Meta ad account for campaign analytics and conversion tracking.</p>
              <MetaTab />
            </>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
