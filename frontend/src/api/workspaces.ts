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
  created_at: string | null;
  has_telethon: boolean;
  has_meta: boolean;
  has_bot_token: boolean;
}

export async function fetchWorkspaces(): Promise<Workspace[]> {
  const res = await fetch(`${API_BASE}/workspaces`, { headers: authHeaders() });
  if (!res.ok) throw new Error("Failed to fetch workspaces");
  return res.json();
}

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
