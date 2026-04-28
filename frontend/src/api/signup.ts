import { saveAuth, AuthUser } from "./auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

export interface OrgSignupBody {
  full_name: string; email: string; password: string;
  org_name: string;
  niche?: string; language?: string; timezone?: string; country?: string;
  main_channel_url?: string; sales_telegram_username?: string;
  meta_pixel_id?: string; meta_ad_account_id?: string; meta_access_token?: string;
}

export async function signupOrganization(body: OrgSignupBody): Promise<AuthUser> {
  const r = await fetch(`${API_BASE}/auth/signup/organization`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.detail || "Signup failed");
  const user: AuthUser = {
    username: j.username, role: j.role, token: j.access_token,
    workspace_id: j.workspace_id, org_id: j.org_id, org_role: j.org_role,
    account_id: j.account_id,
    onboarding_complete: false,
  };
  saveAuth(user);
  return user;
}

export interface InviteLookup {
  workspace_name: string;
  inviter_name: string | null;
  expires_at: string;
}

export const lookupAffiliateInvite = async (token: string): Promise<InviteLookup> => {
  const r = await fetch(`${API_BASE}/auth/affiliate-invites/${token}`);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.detail || "Invite lookup failed");
  return j;
};

export interface AcceptInviteBody {
  full_name: string;
  email: string;
  password: string;
  affiliate_username?: string;
}

export async function acceptAffiliateInvite(token: string, body: AcceptInviteBody): Promise<AuthUser> {
  const r = await fetch(`${API_BASE}/auth/affiliate-invites/${token}/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.detail || "Failed to accept invite");
  const user: AuthUser = {
    username: j.username, role: j.role, token: j.access_token,
    workspace_id: j.workspace_id, org_id: j.org_id, org_role: j.org_role,
    account_id: j.account_id,
    onboarding_complete: false,
  };
  saveAuth(user);
  return user;
}
