import { getToken, clearAuth } from "./auth";
import { MOCK_AFFILIATES } from "./mockData";

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

export interface AffiliatePerformance {
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
  is_active: boolean;
  created_at: string;
}

export interface CreateAffiliatePayload {
  name: string;
  username?: string;
  commission_rate?: number;
}

export const fetchAffiliatePerformance = (): Promise<AffiliatePerformance[]> =>
  MOCK ? Promise.resolve(MOCK_AFFILIATES) : apiFetch("/affiliates/performance");

export const createAffiliate = (payload: CreateAffiliatePayload): Promise<AffiliatePerformance> =>
  MOCK
    ? Promise.resolve({
        id: Date.now(),
        name: payload.name,
        username: payload.username || null,
        referral_tag: "ref_mock1234",
        referral_link: null,
        leads: 0,
        deposits: 0,
        conversion_rate: 0,
        lots_traded: 0,
        commission_rate: payload.commission_rate ?? 15,
        commission_earned: 0,
        is_active: true,
        created_at: new Date().toISOString(),
      })
    : apiFetch("/affiliates", {
        method: "POST",
        body: JSON.stringify(payload),
      });

export const updateAffiliateLots = (affiliateId: number, lots_traded: number): Promise<void> =>
  MOCK
    ? Promise.resolve()
    : apiFetch(`/affiliates/${affiliateId}/lots`, {
        method: "PATCH",
        body: JSON.stringify({ lots_traded }),
      });
