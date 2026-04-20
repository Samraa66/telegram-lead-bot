const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

export type Role = "developer" | "admin" | "operator" | "vip_manager" | "affiliate";

export interface AuthUser {
  username: string;
  role: Role;
  token: string;
}

const TOKEN_KEY = "crm_token";
const USER_KEY = "crm_user";

export function saveAuth(user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, user.token);
  localStorage.setItem(USER_KEY, JSON.stringify({ username: user.username, role: user.role }));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): { username: string; role: Role } | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
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
  const user: AuthUser = { username: json.username, role: json.role, token: json.access_token };
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
  const user: AuthUser = { username: data.username, role: data.role, token: data.access_token };
  saveAuth(user);
  return user;
}
