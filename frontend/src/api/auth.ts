const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

export type Role = "developer" | "admin" | "operator" | "vip_manager" | "affiliate";

export interface AuthUser {
  username: string;
  role: Role;
  token: string;
  workspace_id?: number;
  workspace_name?: string;
  org_id?: number;
  org_role?: string;
  onboarding_complete?: boolean;
  parent_bot_username?: string | null;
}

const TOKEN_KEY = "crm_token";
const USER_KEY = "crm_user";

export function saveAuth(user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, user.token);
  localStorage.setItem(USER_KEY, JSON.stringify({
    username: user.username,
    role: user.role,
    workspace_id: user.workspace_id ?? 1,
    workspace_name: user.workspace_name ?? null,
    org_id: user.org_id ?? 1,
    org_role: user.org_role ?? "member",
    onboarding_complete: user.onboarding_complete ?? true,
    parent_bot_username: user.parent_bot_username ?? null,
  }));
}

export function markOnboardingComplete(): void {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw);
    localStorage.setItem(USER_KEY, JSON.stringify({ ...parsed, onboarding_complete: true }));
  } catch { /* ignore */ }
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): { username: string; role: Role; workspace_id: number; workspace_name: string | null; org_id: number; org_role: string; onboarding_complete: boolean; parent_bot_username: string | null } | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return { workspace_id: 1, workspace_name: null, org_id: 1, org_role: "member", onboarding_complete: true, parent_bot_username: null, ...parsed };
  } catch { return null; }
}

export function canManageAffiliates(role: Role): boolean {
  return role === "developer" || role === "admin";
}

export async function fetchAuthConfig(): Promise<{ bot_username: string }> {
  const res = await fetch(`${API_BASE}/auth/config`);
  return res.json();
}

export interface TelegramAuthData {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

export async function loginWithTelegram(data: TelegramAuthData): Promise<AuthUser> {
  const res = await fetch(`${API_BASE}/auth/telegram`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json?.detail || "Telegram login failed");
  const user: AuthUser = {
    username: json.username, role: json.role, token: json.access_token,
    workspace_id: json.workspace_id ?? 1, org_id: json.org_id ?? 1, org_role: json.org_role ?? "member",
    parent_bot_username: json.parent_bot_username ?? null,
  };
  saveAuth(user);
  return user;
}

export async function login(username: string, password: string): Promise<AuthUser> {
  if (import.meta.env.VITE_USE_MOCK === "true") {
    const user: AuthUser = { username, role: "admin", token: "mock-token" };
    saveAuth(user);
    return user;
  }
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Invalid credentials");
  const user: AuthUser = {
    username: data.username, role: data.role, token: data.access_token,
    workspace_id: data.workspace_id ?? 1, org_id: data.org_id ?? 1, org_role: data.org_role ?? "member",
    onboarding_complete: data.onboarding_complete ?? true,
    parent_bot_username: data.parent_bot_username ?? null,
  };
  saveAuth(user);
  return user;
}

export async function switchWorkspace(workspaceId: number): Promise<{ workspace_name: string }> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/auth/switch-workspace/${workspaceId}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Failed to switch workspace");
  const stored = getStoredUser();
  if (stored) {
    saveAuth({
      username: stored.username, role: stored.role, token: data.access_token,
      workspace_id: workspaceId, workspace_name: data.workspace_name,
      org_id: data.org_id ?? stored.org_id, org_role: stored.org_role,
    });
  }
  return { workspace_name: data.workspace_name };
}
