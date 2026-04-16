import { useEffect, useState } from "react";
import AppLayout from "@/components/AppLayout";
import {
  Keyword, FollowUpTemplate, QuickReply, StageLabel,
  fetchKeywords, createKeyword, updateKeyword, deleteKeyword,
  fetchFollowUpTemplates, updateFollowUpTemplate,
  fetchQuickReplies, createQuickReply, updateQuickReply, deleteQuickReply,
  fetchStageLabels, updateStageLabel,
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

// ---- Main page ----

type Tab = "keywords" | "followups" | "quickreplies" | "stagelabels";

const TABS: { id: Tab; label: string }[] = [
  { id: "keywords", label: "Keywords" },
  { id: "followups", label: "Follow-ups" },
  { id: "quickreplies", label: "Quick Replies" },
  { id: "stagelabels", label: "Stage Labels" },
];

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("keywords");

  return (
    <AppLayout>
      <div className="p-6 max-w-3xl">
        <h1 className="text-xl font-semibold mb-1">Settings</h1>
        <p className="text-sm text-muted-foreground mb-6">Configure your pipeline keywords, follow-up messages, and display labels.</p>

        <div className="flex gap-1 border-b mb-6">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
                tab === t.id
                  ? "border-[hsl(199,86%,55%)] text-[hsl(199,86%,45%)]"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "keywords" && <KeywordsTab />}
        {tab === "followups" && <FollowUpsTab />}
        {tab === "quickreplies" && <QuickRepliesTab />}
        {tab === "stagelabels" && <StageLabelsTab />}
      </div>
    </AppLayout>
  );
}
