import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { signupOrganization } from "../api/signup";

export default function SignupPage() {
  const nav = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", org_name: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await signupOrganization(form);
      nav("/onboarding");
    } catch (err: any) {
      setError(err.message || "Signup failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Create your workspace</h1>
          <p className="text-sm text-muted-foreground">
            Takes about 30 seconds — you can configure everything else in onboarding.
          </p>
        </div>

        {[
          { key: "full_name", label: "Full name", placeholder: "Jane Doe" },
          { key: "email", label: "Email", placeholder: "jane@example.com", type: "email" },
          { key: "password", label: "Password", placeholder: "At least 8 characters", type: "password" },
          { key: "org_name", label: "Organization name", placeholder: "Acme Trading" },
        ].map((f) => (
          <div key={f.key} className="space-y-1.5">
            <label className="block text-xs font-medium text-muted-foreground">{f.label}</label>
            <input
              type={f.type || "text"}
              required
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
          disabled={loading}
          className="w-full h-10 rounded-lg bg-primary text-primary-foreground font-semibold text-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? "Creating…" : "Create account"}
        </button>

        <p className="text-center text-xs text-muted-foreground">
          Already have an account?{" "}
          <Link to="/login" className="text-primary hover:underline">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
