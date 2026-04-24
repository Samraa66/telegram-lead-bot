import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Loader2, Eye, EyeOff, Check } from "lucide-react";
import { lookupInvite, acceptInvite, InviteInfo } from "../api/affiliates";
import { saveAuth } from "../api/auth";

const LogoMark = ({ size = 40 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 36 36" fill="none" aria-hidden>
    <rect width="36" height="36" rx="9" fill="hsl(var(--primary) / 0.12)" />
    <rect width="36" height="36" rx="9" stroke="hsl(var(--primary) / 0.25)" strokeWidth="1" />
    <polyline points="6,27 11,19 16,23 22,12 30,15" stroke="hsl(var(--primary))" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    <circle cx="30" cy="15" r="2.5" fill="hsl(var(--primary))" />
  </svg>
);

export default function InvitePage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    lookupInvite(token)
      .then(setInfo)
      .catch(e => setLoadError(e?.message || "Invite is invalid or expired"));
  }, [token]);

  const mismatch = confirm.length > 0 && password !== confirm;
  const tooShort = password.length > 0 && password.length < 8;
  const canSubmit = !submitting && password.length >= 8 && password === confirm;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await acceptInvite(token, password);
      saveAuth({
        username: res.username,
        role: res.role as any,
        token: res.access_token,
        workspace_id: res.workspace_id,
        org_id: res.org_id,
        org_role: res.org_role,
        onboarding_complete: res.onboarding_complete,
      });
      navigate(res.onboarding_complete ? "/" : "/onboarding");
    } catch (e: any) {
      setError(e?.message || "Could not set password");
      setSubmitting(false);
    }
  }

  // --- Loading / error states -----------------------------------------------

  if (loadError) {
    return (
      <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-4">
        <div className="max-w-sm w-full space-y-4 text-center">
          <LogoMark size={40} />
          <h1 className="text-xl font-semibold tracking-tight">Invite unavailable</h1>
          <p className="text-sm text-muted-foreground">{loadError}</p>
          <p className="text-xs text-muted-foreground">Ask your admin to send you a fresh invite link.</p>
        </div>
      </div>
    );
  }

  if (!info) {
    return (
      <div className="min-h-screen bg-background text-foreground flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // --- Form -----------------------------------------------------------------

  const expiresLabel = info.expires_at
    ? new Date(info.expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : null;

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-4 py-12 page-enter">
      <div className="w-full max-w-sm space-y-7">
        <div className="flex flex-col items-center text-center space-y-3">
          <LogoMark size={44} />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Welcome, {info.name}</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Set a password to activate your workspace.
            </p>
          </div>
        </div>

        <div className="surface-card p-4 space-y-1.5">
          <p className="eyebrow">Your username</p>
          <p className="text-sm font-mono text-foreground">{info.login_username}</p>
          <p className="text-xs text-muted-foreground">You'll use this to sign in from now on.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-muted-foreground">New password</label>
            <div className="relative">
              <input
                type={show ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                autoComplete="new-password"
                className="w-full h-10 rounded-lg px-3.5 pr-10 text-sm text-foreground placeholder:text-muted-foreground/60 bg-secondary/40 border border-border focus:border-primary focus:ring-2 focus:ring-primary/25 outline-none transition-colors"
              />
              <button
                type="button"
                onClick={() => setShow(s => !s)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-1"
                tabIndex={-1}
              >
                {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {tooShort && <p className="text-xs text-destructive">Must be at least 8 characters</p>}
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-muted-foreground">Confirm password</label>
            <input
              type={show ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Re-enter password"
              autoComplete="new-password"
              className="w-full h-10 rounded-lg px-3.5 text-sm text-foreground placeholder:text-muted-foreground/60 bg-secondary/40 border border-border focus:border-primary focus:ring-2 focus:ring-primary/25 outline-none transition-colors"
            />
            {mismatch && <p className="text-xs text-destructive">Passwords don't match</p>}
          </div>

          {error && (
            <div className="rounded-lg px-3.5 py-2.5 bg-destructive/10 border border-destructive/25">
              <p className="text-xs text-destructive text-center">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="w-full h-10 rounded-lg bg-primary text-primary-foreground font-semibold text-sm transition-colors hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Check className="h-4 w-4" /> Activate account</>}
          </button>
        </form>

        {expiresLabel && (
          <p className="text-center text-[11px] text-muted-foreground">
            Invite expires {expiresLabel}
          </p>
        )}
      </div>
    </div>
  );
}
