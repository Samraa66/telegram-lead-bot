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
  // Derived on the server from the affiliate's workspace — NOT editable via PATCH.
  // Always in sync with what onboarding/settings has actually configured.
  has_bot_token?: boolean;
  has_conversion_desk?: boolean;
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
  // Returned once at creation — admin sends this URL to the affiliate
  login_username?: string;
  invite_url?: string;
  invite_expires_at?: string | null;
}

export interface InviteHandoff {
  login_username: string;
  invite_url: string;
  invite_expires_at: string | null;
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

export const resetAffiliateCredentials = (affiliateId: number): Promise<InviteHandoff> =>
  apiFetch(`/affiliates/${affiliateId}/reset-credentials`, { method: "POST" });

// Public invite endpoints — no auth required
export interface InviteInfo {
  name: string;
  login_username: string;
  expires_at: string | null;
}

export const lookupInvite = async (token: string): Promise<InviteInfo> => {
  // Explicit Accept: application/json so the backend SPA-fallback middleware
  // (which only intercepts text/html navigations) lets this reach the API route.
  const res = await fetch(`${API_BASE}/invite/${encodeURIComponent(token)}`, {
    headers: { "Accept": "application/json" },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || `Invite lookup failed (${res.status})`);
  return data;
};

export interface InviteAcceptResponse {
  access_token: string;
  role: string;
  username: string;
  workspace_id: number;
  org_id: number;
  org_role: string;
  onboarding_complete: boolean;
}

export const acceptInvite = async (token: string, password: string): Promise<InviteAcceptResponse> => {
  const res = await fetch(`${API_BASE}/invite/${encodeURIComponent(token)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify({ password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || `Failed to accept invite (${res.status})`);
  return data;
};
