import { getToken, clearAuth } from "./auth";

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

export interface AffiliateChecklist {
  esim_done: boolean;
  free_channel_id: string | null;
  free_channel_members: number;
  bot_setup_done: boolean;
  vip_channel_id: string | null;
  vip_channel_members: number;
  tutorial_channel_id: string | null;
  tutorial_channel_members: number;
  sales_scripts_done: boolean;
  ib_profile_id: string | null;
  ads_live: boolean;
  pixel_setup_done: boolean;
}

export interface AffiliatePerformance extends AffiliateChecklist {
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
  // Returned once at creation only
  login_username?: string;
  login_password?: string;
}

export interface CreateAffiliatePayload {
  name: string;
  username?: string;
  commission_rate?: number;
}

export const fetchAffiliatePerformance = (): Promise<AffiliatePerformance[]> =>
  apiFetch("/affiliates/performance");

export const createAffiliate = (payload: CreateAffiliatePayload): Promise<AffiliatePerformance> =>
  apiFetch("/affiliates", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateAffiliateLots = (affiliateId: number, lots_traded: number): Promise<void> =>
  apiFetch(`/affiliates/${affiliateId}/lots`, {
    method: "PATCH",
    body: JSON.stringify({ lots_traded }),
  });

export const updateAffiliateChecklist = (
  affiliateId: number,
  patch: Partial<AffiliateChecklist>,
): Promise<void> =>
  apiFetch(`/affiliates/${affiliateId}/checklist`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export interface PendingChannel {
  id: number;
  chat_id: string;
  title: string | null;
  detected_at: string;
}

export const fetchPendingChannels = (): Promise<PendingChannel[]> =>
  apiFetch("/affiliates/pending-channels");

export const linkChannel = (
  affiliateId: number,
  chat_id: string,
  channel_type: "free" | "vip" | "tutorial",
): Promise<void> =>
  apiFetch(`/affiliates/${affiliateId}/link-channel`, {
    method: "POST",
    body: JSON.stringify({ chat_id, channel_type }),
  });

export const dismissPendingChannel = (pendingId: number): Promise<void> =>
  apiFetch(`/affiliates/pending-channels/${pendingId}`, { method: "DELETE" });

export const triggerChannelSync = (): Promise<void> =>
  apiFetch("/affiliates/sync-channels", { method: "POST" });

export const deleteAffiliate = (affiliateId: number): Promise<void> =>
  apiFetch(`/affiliates/${affiliateId}`, { method: "DELETE" });
