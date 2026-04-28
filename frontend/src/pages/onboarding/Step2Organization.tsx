import { useState } from "react";
import { getToken } from "../../api/auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

const FIELDS = [
  { key: "niche",                    label: "Niche",                  placeholder: "Forex education" },
  { key: "language",                 label: "Primary language",       placeholder: "en" },
  { key: "timezone",                 label: "Timezone",               placeholder: "Asia/Dubai" },
  { key: "country",                  label: "Country",                placeholder: "United Arab Emirates" },
  { key: "main_channel_url",        label: "Main channel link",      placeholder: "https://t.me/..." },
  { key: "sales_telegram_username", label: "Sales Telegram handle",  placeholder: "@yourname" },
];

interface Props { onNext: () => void; onBack: () => void; onSkip: () => void }

export default function Step2Organization({ onNext, onBack, onSkip }: Props) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSaving(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/settings/workspace`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify(form),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        setError(err?.detail || "Save failed");
        return;
      }
      onNext();
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Tell us about your business</h2>
        <p className="text-sm text-muted-foreground mt-1">
          We use this for analytics, scheduling, and reports. Skip anything you don't know yet.
        </p>
      </div>
      {FIELDS.map((f) => (
        <div key={f.key} className="space-y-1.5">
          <label className="block text-xs font-medium text-muted-foreground">{f.label}</label>
          <input
            value={form[f.key] || ""}
            placeholder={f.placeholder}
            onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
            className="w-full h-10 rounded-lg px-3 text-sm bg-secondary/40 border border-border focus:border-primary focus:ring-2 focus:ring-primary/25 outline-none transition-colors"
          />
        </div>
      ))}
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
      <div className="flex gap-2">
        <button
          onClick={onBack}
          className="px-3 h-10 rounded-lg border border-border text-sm hover:bg-secondary/40 transition-colors">
          Back
        </button>
        <button
          onClick={submit}
          disabled={saving}
          className="flex-1 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold transition-colors hover:bg-primary/90 disabled:opacity-50">
          {saving ? "Saving…" : "Save & continue"}
        </button>
      </div>
      <button onClick={onSkip} className="w-full text-xs text-muted-foreground hover:text-foreground transition-colors">
        Skip for now
      </button>
    </div>
  );
}
