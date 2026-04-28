import { useState } from "react";
import { getToken } from "../../api/auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

const FIELDS = [
  {
    key: "meta_pixel_id",
    label: "Meta Pixel ID",
    placeholder: "123456789012345",
    help: "Business Manager → Events Manager → your pixel → Settings.",
  },
  {
    key: "meta_ad_account_id",
    label: "Meta Ad Account ID",
    placeholder: "act_1234567890",
    help: "Ads Manager URL: facebook.com/adsmanager/manage/?act=<this>.",
  },
  {
    key: "meta_access_token",
    label: "Meta Access Token",
    placeholder: "EAAB…",
    help: "System User token from Business Settings. Stored encrypted at rest.",
  },
];

interface Props { onNext: () => void; onBack: () => void; onSkip: () => void }

export default function Step5Integrations({ onNext, onBack, onSkip }: Props) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSaving(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/settings/meta/credentials`, {
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
        <h2 className="text-lg font-bold text-foreground">Meta integrations</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Optional — needed only if you run paid ads. You can connect later from Settings.
        </p>
      </div>
      {FIELDS.map((f) => (
        <div key={f.key} className="space-y-1">
          <label className="block text-xs font-medium text-muted-foreground">{f.label}</label>
          <input
            value={form[f.key] || ""}
            placeholder={f.placeholder}
            onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
            className="w-full h-10 rounded-lg px-3 text-sm bg-secondary/40 border border-border focus:border-primary focus:ring-2 focus:ring-primary/25 outline-none transition-colors"
          />
          <p className="text-[11px] text-muted-foreground">{f.help}</p>
        </div>
      ))}
      {error && <p className="text-xs text-destructive">{error}</p>}
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
        Skip — set up later
      </button>
    </div>
  );
}
