import { useEffect, useRef, useState } from "react";
import AppLayout from "@/components/AppLayout";
import {
  Keyword, FollowUpTemplate, QuickReply, StageLabel, TeamMember,
  fetchKeywords, createKeyword, updateKeyword, deleteKeyword,
  fetchFollowUpTemplates, updateFollowUpTemplate,
  fetchQuickReplies, createQuickReply, updateQuickReply, deleteQuickReply,
  fetchStageLabels, updateStageLabel,
  fetchTeam, createTeamMember, updateTeamMember, resetTeamPassword, deleteTeamMember,
} from "../api/settings";
import { cn } from "../lib/utils";

// ---- helpers ----

const STAGE_NUMS = [1, 2, 3, 4, 5, 6, 7, 8];

function stageBadge(n: number) {
  return (
    <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[hsl(199,86%,55%)] text-white text-xs font-semibold">
      {n}
    </span>
  );
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
      className="px-3 py-1 text-xs rounded-md bg-[hsl(199,86%,55%)] text-white hover:bg-[hsl(199,86%,45%)] disabled:opacity-50 transition-colors"
    >
      {saving ? "Saving…" : "Save"}
    </button>
  );
}

function DeleteButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="px-2 py-1 text-xs rounded-md text-red-500 hover:bg-red-50 transition-colors"
    >
      Remove
    </button>
  );
}

// ---- Keywords tab ----

function KeywordsTab() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [loading, setLoading] = useState(true);
  const [newKw, setNewKw] = useState("");
  const [newStage, setNewStage] = useState(2);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);
  const [editText, setEditText] = useState<Record<number, string>>({});

  useEffect(() => {
    fetchKeywords()
      .then(setKeywords)
      .finally(() => setLoading(false));
  }, []);

  async function handleAdd() {
    if (!newKw.trim()) return;
    setAdding(true);
    try {
      const created = await createKeyword(newKw.trim(), newStage);
      setKeywords(prev => [...prev, created]);
      setNewKw("");
      setNewStage(2);
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
              <span className="shrink-0">{stageBadge(kw.target_stage)}</span>
              <input
                className="flex-1 text-sm bg-transparent border-none outline-none focus:ring-0"
                value={text}
                onChange={e => setEditText(prev => ({ ...prev, [kw.id]: e.target.value }))}
              />
              {dirty && <SaveButton saving={saving === kw.id} onClick={() => handleSave(kw)} />}
              <button
                onClick={() => handleToggle(kw)}
                className={cn("text-xs px-2 py-1 rounded-md transition-colors", kw.is_active ? "text-muted-foreground hover:bg-muted" : "text-[hsl(199,86%,55%)] hover:bg-blue-50")}
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
          value={newStage}
          onChange={e => setNewStage(Number(e.target.value))}
          className="text-sm border rounded-md px-2 py-1.5 bg-background shrink-0"
        >
          {STAGE_NUMS.slice(1).map(n => <option key={n} value={n}>Stage {n}</option>)}
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
          disabled={adding || !newKw.trim()}
          className="px-3 py-1.5 text-sm rounded-md bg-[hsl(199,86%,55%)] text-white hover:bg-[hsl(199,86%,45%)] disabled:opacity-50 transition-colors shrink-0"
        >
          {adding ? "Adding…" : "Add"}
        </button>
      </div>
    </div>
  );
}

// ---- Follow-up Templates tab ----

function FollowUpsTab() {
  const [templates, setTemplates] = useState<FollowUpTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [editText, setEditText] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState<number | null>(null);

  useEffect(() => {
    fetchFollowUpTemplates()
      .then(setTemplates)
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(tmpl: FollowUpTemplate) {
    setSaving(tmpl.id);
    try {
      const updated = await updateFollowUpTemplate(tmpl.id, editText[tmpl.id] ?? tmpl.message_text);
      setTemplates(prev => prev.map(t => t.id === tmpl.id ? updated : t));
      setEditText(prev => { const n = { ...prev }; delete n[tmpl.id]; return n; });
    } finally {
      setSaving(null);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const grouped = STAGE_NUMS.reduce<Record<number, FollowUpTemplate[]>>((acc, s) => {
    acc[s] = templates.filter(t => t.stage === s);
    return acc;
  }, {});

  return (
    <div>
      <SectionHeader
        title="Follow-up Templates"
        description="Automated messages sent when a lead has not responded. One per stage sequence slot."
      />
      <div className="space-y-6">
        {STAGE_NUMS.map(stage => {
          const rows = grouped[stage];
          if (!rows.length) return null;
          return (
            <div key={stage}>
              <div className="flex items-center gap-2 mb-2">
                {stageBadge(stage)}
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Stage {stage}</span>
              </div>
              <div className="space-y-2 pl-8">
                {rows.map(tmpl => {
                  const text = editText[tmpl.id] ?? tmpl.message_text;
                  const dirty = editText[tmpl.id] !== undefined && editText[tmpl.id] !== tmpl.message_text;
                  return (
                    <div key={tmpl.id} className="rounded-lg border bg-card p-3">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs text-muted-foreground">Follow-up #{tmpl.sequence_num}</span>
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
          );
        })}
      </div>
    </div>
  );
}

// ---- Quick Replies tab ----

function QuickRepliesTab() {
  const [replies, setReplies] = useState<QuickReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<number | null>(null);
  const [editData, setEditData] = useState<Record<number, Partial<QuickReply>>>({});
  const [adding, setAdding] = useState(false);
  const [newForm, setNewForm] = useState({ stage_num: 1, label: "", text: "" });

  useEffect(() => {
    fetchQuickReplies()
      .then(setReplies)
      .finally(() => setLoading(false));
  }, []);

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
    if (!newForm.label.trim() || !newForm.text.trim()) return;
    setAdding(true);
    try {
      const created = await createQuickReply({ ...newForm, sort_order: 0 });
      setReplies(prev => [...prev, created]);
      setNewForm({ stage_num: 1, label: "", text: "" });
    } finally {
      setAdding(false);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const grouped = STAGE_NUMS.reduce<Record<number, QuickReply[]>>((acc, s) => {
    acc[s] = replies.filter(r => r.stage_num === s);
    return acc;
  }, {});

  return (
    <div>
      <SectionHeader
        title="Quick Replies"
        description="Pre-written message buttons shown in the CRM lead drawer, grouped by pipeline stage."
      />
      <div className="space-y-6 mb-8">
        {STAGE_NUMS.map(stage => {
          const rows = grouped[stage];
          if (!rows.length) return null;
          return (
            <div key={stage}>
              <div className="flex items-center gap-2 mb-2">
                {stageBadge(stage)}
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Stage {stage}</span>
              </div>
              <div className="space-y-2 pl-8">
                {rows.map(qr => {
                  const ed = editData[qr.id] ?? {};
                  const label = ed.label ?? qr.label;
                  const text = ed.text ?? qr.text;
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
          );
        })}
      </div>

      <div className="rounded-lg border border-dashed bg-muted/30 p-4">
        <p className="text-xs font-medium text-muted-foreground mb-3">Add new quick reply</p>
        <div className="flex items-center gap-2 mb-2">
          <select
            value={newForm.stage_num}
            onChange={e => setNewForm(f => ({ ...f, stage_num: Number(e.target.value) }))}
            className="text-sm border rounded-md px-2 py-1.5 bg-background"
          >
            {STAGE_NUMS.map(n => <option key={n} value={n}>Stage {n}</option>)}
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
          disabled={adding || !newForm.label.trim() || !newForm.text.trim()}
          className="px-3 py-1.5 text-sm rounded-md bg-[hsl(199,86%,55%)] text-white hover:bg-[hsl(199,86%,45%)] disabled:opacity-50 transition-colors"
        >
          {adding ? "Adding…" : "Add Quick Reply"}
        </button>
      </div>
    </div>
  );
}

// ---- Stage Labels tab ----

function StageLabelsTab() {
  const [labels, setLabels] = useState<StageLabel[]>([]);
  const [loading, setLoading] = useState(true);
  const [editText, setEditText] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState<number | null>(null);

  useEffect(() => {
    fetchStageLabels()
      .then(setLabels)
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(lbl: StageLabel) {
    setSaving(lbl.id);
    try {
      const updated = await updateStageLabel(lbl.id, editText[lbl.id] ?? lbl.label);
      setLabels(prev => prev.map(l => l.id === lbl.id ? updated : l));
      setEditText(prev => { const n = { ...prev }; delete n[lbl.id]; return n; });
    } finally {
      setSaving(null);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div>
      <SectionHeader
        title="Stage Labels"
        description="Display names for each pipeline stage. Changes here are stored per workspace and will be used when multi-workspace support is enabled."
      />
      <div className="space-y-2">
        {labels.map(lbl => {
          const text = editText[lbl.id] ?? lbl.label;
          const dirty = editText[lbl.id] !== undefined && editText[lbl.id] !== lbl.label;
          return (
            <div key={lbl.id} className="flex items-center gap-3 px-3 py-2 rounded-lg border bg-card">
              {stageBadge(lbl.stage_num)}
              <input
                className="flex-1 text-sm bg-transparent border-none outline-none"
                value={text}
                onChange={e => setEditText(prev => ({ ...prev, [lbl.id]: e.target.value }))}
              />
              {dirty && <SaveButton saving={saving === lbl.id} onClick={() => handleSave(lbl)} />}
            </div>
          );
        })}
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
        {error && <p className="text-xs text-red-500 mb-2">{error}</p>}
        <button
          onClick={handleCreate}
          disabled={adding || !form.display_name.trim() || !form.username.trim()}
          className="px-3 py-1.5 text-sm rounded-md bg-[hsl(199,86%,55%)] text-white hover:bg-[hsl(199,86%,45%)] disabled:opacity-50 transition-colors"
        >
          {adding ? "Creating…" : "Add Member"}
        </button>
      </div>
    </div>
  );
}

// ---- Main page ----

// ---- Meta Integration Tab ----

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

function MetaTab() {
  const [status, setStatus] = useState<{ connected: boolean; ad_account_id: string | null; pixel_id: string | null } | null>(null);
  const [accounts, setAccounts] = useState<{ id: string; name: string }[]>([]);
  const [selectedAccount, setSelectedAccount] = useState("");
  const [pixelId, setPixelId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const hasLoadedAccounts = useRef(false);

  useEffect(() => {
    const token = localStorage.getItem("crm_token");
    fetch(`${API_BASE}/settings/meta/status`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(setStatus)
      .catch(() => {});

    // If returning from OAuth, load ad accounts
    const params = new URLSearchParams(window.location.search);
    if (params.get("meta_connected") === "1" && !hasLoadedAccounts.current) {
      hasLoadedAccounts.current = true;
      fetch(`${API_BASE}/settings/meta/accounts`, { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(d => setAccounts(d.accounts || []))
        .catch(() => {});
      // Clean up URL
      window.history.replaceState({}, "", window.location.pathname + "#meta");
    }
  }, []);

  async function handleConnect() {
    const token = localStorage.getItem("crm_token");
    const res = await fetch(`${API_BASE}/auth/meta/connect`, { headers: { Authorization: `Bearer ${token}` } });
    const data = await res.json();
    if (data.url) window.location.href = data.url;
  }

  async function handleSaveAccount() {
    if (!selectedAccount || !pixelId.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const token = localStorage.getItem("crm_token");
      const res = await fetch(`${API_BASE}/settings/meta/account`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ ad_account_id: selectedAccount, pixel_id: pixelId.trim() }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed");
      setSuccess(true);
      setStatus(s => s ? { ...s, ad_account_id: selectedAccount, pixel_id: pixelId.trim() } : s);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Meta Integration"
        description="Connect your Meta ad account to pull campaign analytics and fire conversion events automatically."
      />

      <div className="rounded-lg border bg-card p-4 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Meta Ads Account</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {status?.connected
                ? status.ad_account_id
                  ? `Connected — ${status.ad_account_id}`
                  : "Token saved — select an ad account below"
                : "Not connected"}
            </p>
          </div>
          <button
            onClick={handleConnect}
            className="px-3 py-1.5 text-sm rounded-md bg-[#1877F2] text-white hover:bg-[#166FE5] transition-colors shrink-0"
          >
            {status?.connected ? "Reconnect" : "Connect Meta Account"}
          </button>
        </div>

        {status?.pixel_id && (
          <p className="text-xs text-muted-foreground">Pixel ID: {status.pixel_id}</p>
        )}
      </div>

      {accounts.length > 0 && (
        <div className="rounded-lg border border-dashed bg-muted/30 p-4 space-y-3">
          <p className="text-xs font-medium text-muted-foreground">Select ad account &amp; pixel</p>
          <select
            value={selectedAccount}
            onChange={e => setSelectedAccount(e.target.value)}
            className="w-full text-sm border rounded-md px-3 py-2 bg-background"
          >
            <option value="">Select ad account…</option>
            {accounts.map(a => (
              <option key={a.id} value={a.id}>{a.name} ({a.id})</option>
            ))}
          </select>
          <input
            className="w-full text-sm border rounded-md px-3 py-1.5 bg-background"
            placeholder="Pixel ID (e.g. 123456789)"
            value={pixelId}
            onChange={e => setPixelId(e.target.value)}
          />
          {error && <p className="text-xs text-red-500">{error}</p>}
          {success && <p className="text-xs text-green-600">Saved successfully.</p>}
          <button
            onClick={handleSaveAccount}
            disabled={saving || !selectedAccount || !pixelId.trim()}
            className="px-3 py-1.5 text-sm rounded-md bg-[hsl(199,86%,55%)] text-white hover:bg-[hsl(199,86%,45%)] disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}

// ---- Main page ----

type Section = "pipeline" | "team" | "meta";
type PipelineTab = "keywords" | "followups" | "quickreplies" | "stagelabels";

const SECTIONS: { id: Section; label: string; description: string }[] = [
  { id: "pipeline", label: "Pipeline", description: "Keywords, follow-ups, quick replies, and stage labels" },
  { id: "team",     label: "Team",     description: "Manage operator and manager accounts" },
  { id: "meta",     label: "Meta Ads", description: "Connect your Meta ad account" },
];

const PIPELINE_TABS: { id: PipelineTab; label: string }[] = [
  { id: "keywords",     label: "Keywords" },
  { id: "followups",    label: "Follow-ups" },
  { id: "quickreplies", label: "Quick Replies" },
  { id: "stagelabels",  label: "Stage Labels" },
];

export default function SettingsPage() {
  const [section, setSection] = useState<Section>("pipeline");
  const [pipelineTab, setPipelineTab] = useState<PipelineTab>("keywords");

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
                    ? "bg-[hsl(199,86%,55%)]/10 text-[hsl(199,86%,45%)] font-medium"
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
                        ? "border-[hsl(199,86%,55%)] text-[hsl(199,86%,45%)]"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {pipelineTab === "keywords"     && <KeywordsTab />}
              {pipelineTab === "followups"    && <FollowUpsTab />}
              {pipelineTab === "quickreplies" && <QuickRepliesTab />}
              {pipelineTab === "stagelabels"  && <StageLabelsTab />}
            </>
          )}

          {section === "meta" && (
            <>
              <h2 className="text-lg font-semibold mb-0.5">Meta Ads</h2>
              <p className="text-sm text-muted-foreground mb-6">Connect your Meta ad account for campaign analytics and CAPI.</p>
              <MetaTab />
            </>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
