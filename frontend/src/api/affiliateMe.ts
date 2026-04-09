import { getToken, clearAuth } from "./auth";
import { AffiliateChecklist } from "./affiliates";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

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

export interface AffiliateProfile extends AffiliateChecklist {
  id: number;
  name: string;
  username: string | null;
  referral_tag: string;
  referral_link: string | null;
  leads: number;
  deposits: number;
  conversion_rate: number;
  lots_traded: number;
  commission_rate: number;
  commission_earned: number;
}

export const fetchMyProfile = (): Promise<AffiliateProfile> =>
  apiFetch("/affiliate/me");

export const updateMyChecklist = (patch: Partial<AffiliateChecklist>): Promise<void> =>
  apiFetch("/affiliate/me/checklist", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
