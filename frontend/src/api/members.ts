import { getToken, clearAuth } from "./auth";
import { MOCK_MEMBERS } from "./mockData";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

const MOCK = import.meta.env.VITE_USE_MOCK === "true";

async function apiFetch(path: string, init?: RequestInit) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401) {
    clearAuth();
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`);
  return data;
}

export type ActivityStatus = "active" | "at_risk" | "churned" | "high_value";

export interface VipMember {
  id: string;
  name: string;
  username: string;
  avatar: string;
  stage: number;
  activity_status: ActivityStatus;
  days_inactive: number | null;
  last_activity_at: string | null;
  deposit_date: string | null;
  notes: string;
  classification: string;
}

export const fetchMembers = (): Promise<VipMember[]> =>
  MOCK ? Promise.resolve(MOCK_MEMBERS) : apiFetch("/members");

export const confirmDeposit = (contactId: string): Promise<void> =>
  MOCK
    ? Promise.resolve()
    : apiFetch(`/contacts/${contactId}/deposit-confirm`, { method: "POST" });

export const reengageMember = (contactId: string, message?: string): Promise<void> =>
  MOCK
    ? Promise.resolve()
    : apiFetch(`/members/${contactId}/reengage`, {
        method: "POST",
        body: JSON.stringify({ message: message || null }),
      });
