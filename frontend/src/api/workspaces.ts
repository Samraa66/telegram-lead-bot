const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

function authHeaders() {
  const token = localStorage.getItem("crm_token");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

export interface Workspace {
  id: number;
  name: string;
  org_id: number;
  parent_workspace_id: number | null;
  root_workspace_id: number | null;
  workspace_role: "owner" | "affiliate";
  created_at: string | null;
  has_telethon: boolean;
  has_meta: boolean;
  has_bot_token: boolean;
  // Populated by the developer-only system-level list endpoint:
  org_name?: string | null;
  owner_email?: string | null;
  owner_account_id?: number | null;
  onboarding_complete?: boolean;
}

export interface ImpersonateResponse {
  access_token: string;
  role: string;
  username: string;
  workspace_id: number;
  workspace_name: string;
  org_id: number;
  org_role: string;
  account_id: number;
  onboarding_complete: boolean;
  parent_bot_username: string | null;
}

// Developer-only: mint a JWT impersonating the org-owner of `workspaceId`.
export async function impersonateWorkspace(workspaceId: number): Promise<ImpersonateResponse> {
  const res = await fetch(`${API_BASE}/admin/impersonate/${workspaceId}`, {
    method: "POST",
    headers: authHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Failed to impersonate workspace");
  return data;
}

// System-level list (developer only — all workspaces across all orgs)
export async function fetchWorkspaces(): Promise<Workspace[]> {
  const res = await fetch(`${API_BASE}/workspaces`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Failed to fetch workspaces");
  return res.json();
}

// Org-scoped list (org owners — workspaces in their own org only)
export async function fetchOrgWorkspaces(): Promise<Workspace[]> {
  const res = await fetch(`${API_BASE}/org/workspaces`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Failed to fetch org workspaces");
  return res.json();
}

// Create a child workspace under the caller's org
export async function createOrgWorkspace(
  name: string,
  parentWorkspaceId?: number,
): Promise<Workspace> {
  const res = await fetch(`${API_BASE}/org/workspaces`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ name, parent_workspace_id: parentWorkspaceId ?? null }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Failed to create workspace");
  return data;
}

// System-level create (developer only)
export async function createWorkspace(name: string): Promise<Workspace> {
  const res = await fetch(`${API_BASE}/workspaces`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ name }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Failed to create workspace");
  return data;
}
