import { useEffect, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { fetchAuthConfig, login, loginWithTelegram, TelegramAuthData } from "../api/auth";

const LogoMark = ({ size = 36 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 36 36" fill="none" aria-hidden>
    <rect width="36" height="36" rx="9" fill="hsl(var(--primary) / 0.12)" />
    <rect width="36" height="36" rx="9" stroke="hsl(var(--primary) / 0.25)" strokeWidth="1" />
    <polyline
      points="6,27 11,19 16,23 22,12 30,15"
      stroke="hsl(var(--primary))"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    <circle cx="30" cy="15" r="2.5" fill="hsl(var(--primary))" />
  </svg>
);

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [botUsername, setBotUsername] = useState<string | null>(null);
  const telegramRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchAuthConfig().then(cfg => setBotUsername(cfg.bot_username)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!botUsername || !telegramRef.current) return;
    const container = telegramRef.current;
    container.innerHTML = "";

    (window as any).onTelegramAuth = async (data: TelegramAuthData) => {
      setLoading(true);
      setError(null);
      try {
        const user = await loginWithTelegram(data);
        navigate(user.role === "affiliate" ? "/portal" : "/");
      } catch (err: any) {
        setError(err?.message || "Telegram login failed");
      } finally {
        setLoading(false);
      }
    };

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    script.setAttribute("data-request-access", "write");
    script.async = true;
    container.appendChild(script);

    return () => { container.innerHTML = ""; delete (window as any).onTelegramAuth; };
  }, [botUsername]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const user = await login(username, password);
      navigate(user.role === "affiliate" ? "/portal" : "/");
    } catch (err: any) {
      setError(err?.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex">
      {/* ── Left branding panel (desktop only) ── */}
      <div className="hidden lg:flex flex-col justify-between w-[52%] p-14 relative overflow-hidden border-r border-border/50">
        {/* Dot-grid background */}
        <div
          className="absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              "radial-gradient(circle, hsl(var(--primary) / 0.18) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />

        {/* Bottom-left glow */}
        <div
          className="absolute -bottom-40 -left-40 w-[520px] h-[520px] rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle, hsl(var(--primary) / 0.10) 0%, transparent 65%)",
          }}
        />

        {/* Top-right glow */}
        <div
          className="absolute -top-20 -right-10 w-72 h-72 rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle, hsl(var(--primary) / 0.06) 0%, transparent 70%)",
          }}
        />

        {/* Brand mark */}
        <div className="relative flex items-center gap-3">
          <LogoMark size={36} />
          <span className="text-foreground font-semibold text-base tracking-tight">
            Telelytics
          </span>
        </div>

        {/* Hero copy */}
        <div className="relative space-y-5">
          <p className="eyebrow text-primary/90">Lead, conversion, and affiliate intelligence</p>
          <h2 className="text-[2rem] font-bold text-foreground leading-[1.15] tracking-tight">
            See where leads come from.
            <br />
            Understand what converts.
            <br />
            <span className="text-primary">Track partner performance.</span>
          </h2>
          <p className="text-sm text-muted-foreground leading-relaxed max-w-[340px]">
            All your data across Telegram and Meta in one system.
          </p>
        </div>

        {/* Stats row */}
        <div className="relative flex gap-10">
          {[
            { label: "Active Leads", value: "2.4K" },
            { label: "Avg. Conversion", value: "68%" },
            { label: "Affiliates", value: "12" },
          ].map((stat) => (
            <div key={stat.label}>
              <div className="text-2xl font-bold font-mono text-primary tabular-nums">
                {stat.value}
              </div>
              <div className="text-[10px] text-muted-foreground uppercase tracking-widest mt-1">
                {stat.label}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right form panel ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-[360px] space-y-7">
          {/* Mobile logo */}
          <div className="lg:hidden flex flex-col items-center gap-3 mb-2">
            <LogoMark size={44} />
            <span className="text-foreground font-semibold text-sm tracking-tight">
              Telelytics
            </span>
          </div>

          {/* Heading */}
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold text-foreground tracking-tight">
              Welcome back
            </h1>
            <p className="text-sm text-muted-foreground">Sign in to your workspace</p>
          </div>

          {/* Telegram Login Widget */}
          {botUsername && (
            <div className="space-y-4">
              <div ref={telegramRef} className="flex justify-center" />
              <div className="flex items-center gap-3">
                <div className="flex-1 h-px bg-border" />
                <span className="text-[10px] text-muted-foreground uppercase tracking-[0.2em]">or</span>
                <div className="flex-1 h-px bg-border" />
              </div>
            </div>
          )}

          {/* Form */}
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-muted-foreground">
                Username
              </label>
              <input
                type="text"
                autoCapitalize="none"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter username"
                required
                className="w-full h-10 rounded-lg px-3.5 text-sm text-foreground placeholder:text-muted-foreground/60 bg-secondary/40 border border-border focus:border-primary focus:ring-2 focus:ring-primary/25 outline-none transition-colors"
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-muted-foreground">
                Password
              </label>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                required
                className="w-full h-10 rounded-lg px-3.5 text-sm text-foreground placeholder:text-muted-foreground/60 bg-secondary/40 border border-border focus:border-primary focus:ring-2 focus:ring-primary/25 outline-none transition-colors"
              />
            </div>

            {error && (
              <div className="rounded-lg px-3.5 py-2.5 bg-destructive/10 border border-destructive/25">
                <p className="text-xs text-destructive text-center">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full h-10 mt-1 rounded-lg bg-primary text-primary-foreground font-semibold text-sm transition-colors hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="text-center text-xs text-muted-foreground">
            Don't have an account?{" "}
            <Link to="/signup" className="text-primary hover:underline">Sign up</Link>
          </p>

          <p className="text-center text-[10px] text-muted-foreground/60 tracking-[0.2em] uppercase">
            Authorized access only
          </p>
        </div>
      </div>
    </div>
  );
}
