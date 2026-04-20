import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchAuthConfig, login, loginWithTelegram, TelegramAuthData } from "../api/auth";

const LogoMark = ({ size = 36 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 36 36" fill="none">
    <rect
      width="36"
      height="36"
      rx="9"
      fill="hsl(199,86%,55%)"
      fillOpacity="0.12"
    />
    <rect
      width="36"
      height="36"
      rx="9"
      stroke="hsl(199,86%,55%)"
      strokeOpacity="0.25"
      strokeWidth="1"
    />
    <polyline
      points="6,27 11,19 16,23 22,12 30,15"
      stroke="hsl(199,86%,55%)"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    <circle cx="30" cy="15" r="2.5" fill="hsl(199,86%,55%)" />
    <line
      x1="6"
      y1="29"
      x2="30"
      y2="29"
      stroke="hsl(199,86%,55%)"
      strokeOpacity="0.2"
      strokeWidth="1"
    />
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
    <div className="min-h-screen bg-[#07090d] flex">
      {/* ── Left branding panel (desktop only) ── */}
      <div className="hidden lg:flex flex-col justify-between w-[52%] p-14 relative overflow-hidden border-r border-white/[0.04]">
        {/* Dot-grid background */}
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              "radial-gradient(circle, rgba(14,165,233,0.18) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />

        {/* Bottom-left glow */}
        <div
          className="absolute -bottom-32 -left-32 w-[480px] h-[480px] rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle, hsl(199,86%,55%) 0%, transparent 65%)",
            opacity: 0.08,
          }}
        />

        {/* Top-right subtle glow */}
        <div
          className="absolute -top-20 right-0 w-64 h-64 rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle, hsl(199,86%,55%) 0%, transparent 70%)",
            opacity: 0.04,
          }}
        />

        {/* Brand mark */}
        <div className="relative flex items-center gap-3">
          <LogoMark size={36} />
          <span className="text-white/90 font-semibold text-base tracking-tight">
            Telelytics
          </span>
        </div>

        {/* Hero copy */}
        <div className="relative space-y-5">
          <p
            className="text-xs font-mono tracking-[0.2em] uppercase"
            style={{ color: "hsl(199,86%,55%)" }}
          >
            Intelligence Platform
          </p>
          <h2 className="text-[2.6rem] font-bold text-white leading-[1.15] tracking-tight">
            Every lead.
            <br />
            Every signal.
            <br />
            <span style={{ color: "hsl(199,86%,55%)" }}>All in one place.</span>
          </h2>
          <p className="text-sm text-white/25 leading-relaxed max-w-[300px]">
            Full-spectrum lead tracking, conversion analytics, and affiliate
            performance — unified in a single command center.
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
              <div
                className="text-2xl font-bold font-mono"
                style={{ color: "hsl(199,86%,62%)" }}
              >
                {stat.value}
              </div>
              <div className="text-[10px] text-white/20 uppercase tracking-widest mt-1">
                {stat.label}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right form panel ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-[340px] space-y-8">
          {/* Mobile logo */}
          <div className="lg:hidden flex flex-col items-center gap-3 mb-4">
            <LogoMark size={44} />
            <span className="text-white/80 font-semibold text-sm tracking-tight">
              CRM Dashboard
            </span>
          </div>

          {/* Heading */}
          <div className="space-y-1">
            <h1 className="text-[1.6rem] font-bold text-white tracking-tight">
              Welcome back
            </h1>
            <p className="text-sm text-white/25">Sign in to your account</p>
          </div>

          {/* Telegram Login Widget */}
          {botUsername && (
            <div className="space-y-3">
              <div ref={telegramRef} className="flex justify-center" />
              <div className="flex items-center gap-3">
                <div className="flex-1 h-px bg-white/[0.06]" />
                <span className="text-[10px] text-white/20 uppercase tracking-widest">or</span>
                <div className="flex-1 h-px bg-white/[0.06]" />
              </div>
            </div>
          )}

          {/* Form */}
          <div className="space-y-4">
            {/* Username */}
            <div className="space-y-2">
              <label className="block text-[10px] font-semibold text-white/30 uppercase tracking-[0.15em]">
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
                className="w-full rounded-xl px-4 py-3 text-sm text-white/90 placeholder-white/15 outline-none transition-all"
                style={{
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.07)",
                  boxShadow: "inset 0 1px 4px rgba(0,0,0,0.3)",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.border = "1px solid hsl(199,86%,55%)";
                  e.currentTarget.style.boxShadow =
                    "0 0 0 3px hsl(152,60%,48%,0.1), inset 0 1px 4px rgba(0,0,0,0.3)";
                }}
                onBlur={(e) => {
                  e.currentTarget.style.border =
                    "1px solid rgba(255,255,255,0.07)";
                  e.currentTarget.style.boxShadow =
                    "inset 0 1px 4px rgba(0,0,0,0.3)";
                }}
              />
            </div>

            {/* Password */}
            <div className="space-y-2">
              <label className="block text-[10px] font-semibold text-white/30 uppercase tracking-[0.15em]">
                Password
              </label>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                required
                className="w-full rounded-xl px-4 py-3 text-sm text-white/90 placeholder-white/15 outline-none transition-all"
                style={{
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.07)",
                  boxShadow: "inset 0 1px 4px rgba(0,0,0,0.3)",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.border = "1px solid hsl(199,86%,55%)";
                  e.currentTarget.style.boxShadow =
                    "0 0 0 3px hsl(152,60%,48%,0.1), inset 0 1px 4px rgba(0,0,0,0.3)";
                }}
                onBlur={(e) => {
                  e.currentTarget.style.border =
                    "1px solid rgba(255,255,255,0.07)";
                  e.currentTarget.style.boxShadow =
                    "inset 0 1px 4px rgba(0,0,0,0.3)";
                }}
              />
            </div>

            {/* Error */}
            {error && (
              <div
                className="rounded-xl px-4 py-2.5"
                style={{
                  background: "rgba(239,68,68,0.08)",
                  border: "1px solid rgba(239,68,68,0.2)",
                }}
              >
                <p className="text-xs text-red-400 text-center">{error}</p>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              onClick={handleSubmit}
              disabled={loading}
              className="w-full font-semibold text-sm py-3 rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed mt-1"
              style={{
                background: "hsl(199,86%,55%)",
                color: "#050d14",
                boxShadow: loading
                  ? "none"
                  : "0 0 24px hsl(152,60%,48%,0.28), 0 1px 0 rgba(255,255,255,0.1) inset",
              }}
              onMouseEnter={(e) => {
                if (!loading)
                  e.currentTarget.style.background = "hsl(199,86%,62%)";
              }}
              onMouseLeave={(e) => {
                if (!loading)
                  e.currentTarget.style.background = "hsl(199,86%,55%)";
              }}
            >
              {loading ? "Signing in…" : "Sign In"}
            </button>
          </div>

          <p className="text-center text-[10px] text-white/10 tracking-widest uppercase">
            Authorized access only
          </p>
        </div>
      </div>
    </div>
  );
}
