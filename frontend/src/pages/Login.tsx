import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/auth";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password);
      navigate("/");
    } catch (err: any) {
      setError(err?.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[hsl(220,20%,5%)] flex items-center justify-center p-4">
      <div className="w-full max-w-sm">

        {/* Logo / title */}
        <div className="text-center mb-8 space-y-1">
          <div className="inline-flex items-center justify-center h-14 w-14 rounded-2xl bg-[hsl(152,60%,48%)/15] mb-3">
            <span className="text-2xl">📊</span>
          </div>
          <h1 className="text-xl font-bold text-[hsl(210,20%,92%)]">CRM Dashboard</h1>
          <p className="text-sm text-[hsl(215,12%,52%)]">Sign in to your account</p>
        </div>

        {/* Card */}
        <div className="bg-[hsl(220,18%,10%)] rounded-2xl border border-[hsl(220,14%,16%)] p-6 space-y-4">

          {/* Username */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-[hsl(215,12%,52%)] uppercase tracking-wider">
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
              className="w-full bg-[hsl(220,16%,14%)] border border-[hsl(220,14%,20%)] rounded-xl px-4 py-3 text-sm text-[hsl(210,20%,92%)] placeholder-[hsl(215,12%,38%)] outline-none focus:border-[hsl(152,60%,48%)] focus:ring-1 focus:ring-[hsl(152,60%,48%)] transition-colors"
            />
          </div>

          {/* Password */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-[hsl(215,12%,52%)] uppercase tracking-wider">
              Password
            </label>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              required
              className="w-full bg-[hsl(220,16%,14%)] border border-[hsl(220,14%,20%)] rounded-xl px-4 py-3 text-sm text-[hsl(210,20%,92%)] placeholder-[hsl(215,12%,38%)] outline-none focus:border-[hsl(152,60%,48%)] focus:ring-1 focus:ring-[hsl(152,60%,48%)] transition-colors"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="bg-[hsl(0,72%,56%)/10] border border-[hsl(0,72%,56%)/30] rounded-xl px-4 py-2.5">
              <p className="text-xs text-[hsl(0,72%,70%)] text-center">{error}</p>
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            onClick={handleSubmit}
            disabled={loading}
            className="w-full bg-[hsl(152,60%,48%)] hover:bg-[hsl(152,60%,42%)] disabled:opacity-50 disabled:cursor-not-allowed text-[hsl(220,20%,7%)] font-semibold text-sm py-3 rounded-xl transition-colors"
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </div>
      </div>
    </div>
  );
}
