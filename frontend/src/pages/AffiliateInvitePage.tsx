import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { lookupAffiliateInvite, acceptAffiliateInvite, InviteLookup } from "../api/signup";

export default function AffiliateInvitePage() {
  const { token = "" } = useParams<{ token: string }>();
  const nav = useNavigate();

  const [info, setInfo] = useState<InviteLookup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [form, setForm] = useState({
    full_name: "", email: "", password: "", affiliate_username: "",
  });

  useEffect(() => {
    let cancelled = false;
    lookupAffiliateInvite(token)
      .then((r) => { if (!cancelled) setInfo(r); })
      .catch((e: any) => { if (!cancelled) setError(e.message || "Invalid invite"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await acceptAffiliateInvite(token, {
        full_name: form.full_name,
        email: form.email,
        password: form.password,
        affiliate_username: form.affiliate_username || undefined,
      });
      nav("/onboarding");
    } catch (err: any) {
      setError(err.message || "Failed to accept invite");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-muted-foreground">
        Loading invite…
      </div>
    );
  }

  if (error && !info) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="max-w-sm space-y-3 text-center">
          <h1 className="text-xl font-semibold">Invite unavailable</h1>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Link to="/login" className="text-primary text-sm hover:underline">Back to sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Join {info?.workspace_name ?? "the workspace"}</h1>
          <p className="text-sm text-muted-foreground">
            {info?.inviter_name ? `${info.inviter_name} invited you.` : "Set up your affiliate account."}
            {" "}Choose your password to continue.
          </p>
        </div>

        {[
          { key: "full_name", label: "Full name", placeholder: "Alice Doe" },
          { key: "email", label: "Email", placeholder: "alice@example.com", type: "email" },
          { key: "password", label: "Password", placeholder: "At least 8 characters", type: "password" },
          { key: "affiliate_username", label: "Telegram handle (optional)", placeholder: "@yourname" },
        ].map((f) => (
          <div key={f.key} className="space-y-1.5">
            <label className="block text-xs font-medium text-muted-foreground">{f.label}</label>
            <input
              type={f.type || "text"}
              required={f.key !== "affiliate_username"}
              autoComplete={f.key === "password" ? "new-password" : f.key === "email" ? "email" : "off"}
              value={(form as any)[f.key]}
              placeholder={f.placeholder}
              onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
              className="w-full h-10 rounded-lg px-3 text-sm bg-secondary/40 border border-border focus:border-primary focus:ring-2 focus:ring-primary/25 outline-none transition-colors"
            />
          </div>
        ))}

        {error && (
          <div className="rounded-lg px-3.5 py-2.5 bg-destructive/10 border border-destructive/25">
            <p className="text-xs text-destructive">{error}</p>
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full h-10 rounded-lg bg-primary text-primary-foreground font-semibold text-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {submitting ? "Joining…" : "Accept invite"}
        </button>
      </form>
    </div>
  );
}
