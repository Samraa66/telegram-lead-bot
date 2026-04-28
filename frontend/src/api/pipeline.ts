import { getToken, clearAuth } from "./auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

async function api(path: string, init?: RequestInit) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    ...init,
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

export interface PipelineStage {
  id: number;
  position: number;
  name: string;
  description: string | null;
  color: string | null;
  is_deposit_stage: boolean;
  is_member_stage: boolean;
  is_conversion_stage: boolean;
  end_action: string;
  revert_to_stage_id: number | null;
}

export interface PipelineConfig {
  stages: PipelineStage[];
  deposited_stage_id: number | null;
  member_stage_id: number | null;
  conversion_stage_id: number | null;
  vip_marker_phrases: string[];
}

export const fetchPipeline = (): Promise<PipelineConfig> => api("/settings/pipeline");

export const createStage = (body: Partial<PipelineStage>): Promise<PipelineStage> =>
  api("/settings/pipeline/stages", { method: "POST", body: JSON.stringify(body) });

export const updateStage = (id: number, body: Partial<PipelineStage>): Promise<PipelineStage> =>
  api(`/settings/pipeline/stages/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteStage = (id: number, move_contacts_to?: number) => {
  const q = move_contacts_to ? `?move_contacts_to=${move_contacts_to}` : "";
  return api(`/settings/pipeline/stages/${id}${q}`, { method: "DELETE" });
};

export const reorderStages = (ordered_ids: number[]) =>
  api("/settings/pipeline/reorder", { method: "POST", body: JSON.stringify({ ordered_ids }) });

export const updateFlags = (body: Partial<PipelineConfig>) =>
  api("/settings/pipeline/flags", { method: "PATCH", body: JSON.stringify(body) });
