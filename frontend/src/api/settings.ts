import { getToken } from "./auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

async function apiFetch(path: string, init?: RequestInit) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ---- Types ----

export interface Keyword {
  id: number;
  keyword: string;
  target_stage_id: number;
  target_stage: number;     // legacy mirror
  is_active: boolean;
}

export interface FollowUpTemplate {
  id: number;
  stage: number;
  stage_id: number | null;
  sequence_num: number;
  hours_offset: number;
  message_text: string;
}

export interface QuickReply {
  id: number;
  stage_id: number;
  stage_num: number;        // legacy mirror
  label: string;
  text: string;
  sort_order: number;
  is_active: boolean;
}

export interface StageLabel {
  id: number;
  stage_num: number;
  label: string;
}

// ---- Keywords ----

export const fetchKeywords = (): Promise<Keyword[]> =>
  apiFetch("/settings/keywords");

export const createKeyword = (keyword: string, target_stage_id: number): Promise<Keyword> =>
  apiFetch("/settings/keywords", {
    method: "POST",
    body: JSON.stringify({ keyword, target_stage_id }),
  });

export const updateKeyword = (id: number, body: { keyword?: string; target_stage_id?: number; is_active?: boolean }) =>
  apiFetch(`/settings/keywords/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteKeyword = (id: number): Promise<void> =>
  apiFetch(`/settings/keywords/${id}`, { method: "DELETE" });

// ---- Follow-up Templates ----

export const fetchFollowUpTemplates = (): Promise<FollowUpTemplate[]> =>
  apiFetch("/settings/follow-up-templates");

export const updateFollowUpTemplate = (id: number, message_text: string): Promise<FollowUpTemplate> =>
  apiFetch(`/settings/follow-up-templates/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ message_text }),
  });

export const updateFollowUp = (id: number, body: { message_text?: string; hours_offset?: number }) =>
  apiFetch(`/settings/follow-up-templates/${id}`, { method: "PATCH", body: JSON.stringify(body) });

// ---- Quick Replies ----

export const fetchQuickReplies = (): Promise<QuickReply[]> =>
  apiFetch("/settings/quick-replies");

export const createQuickReply = (stage_id: number, label: string, text: string, sort_order = 0): Promise<QuickReply> =>
  apiFetch("/settings/quick-replies", {
    method: "POST",
    body: JSON.stringify({ stage_id, label, text, sort_order }),
  });

export const updateQuickReply = (id: number, body: { stage_id?: number; label?: string; text?: string; sort_order?: number; is_active?: boolean }): Promise<QuickReply> =>
  apiFetch(`/settings/quick-replies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteQuickReply = (id: number): Promise<void> =>
  apiFetch(`/settings/quick-replies/${id}`, { method: "DELETE" });

// ---- Stage Labels (kept for legacy reads) ----

export const fetchStageLabels = (): Promise<StageLabel[]> =>
  apiFetch("/settings/stage-labels");

export const updateStageLabel = (id: number, label: string): Promise<StageLabel> =>
  apiFetch(`/settings/stage-labels/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ label }),
  });

// ---- Team ----

export interface TeamMember {
  id: number;
  display_name: string;
  username: string;
  role: string;
  is_active: boolean;
  auth_type: "telegram" | "password";
  created_at: string | null;
  password?: string; // only present on create / reset (password auth_type only)
}

export const fetchTeam = (): Promise<TeamMember[]> =>
  apiFetch("/settings/team");

export const createTeamMember = (
  display_name: string,
  username: string,
  role: string,
  auth_type: "telegram" | "password" = "telegram",
): Promise<TeamMember> =>
  apiFetch("/settings/team", {
    method: "POST",
    body: JSON.stringify({ display_name, username, role, auth_type }),
  });

export const updateTeamMember = (
  id: number,
  data: Partial<Pick<TeamMember, "display_name" | "role" | "is_active">>,
): Promise<TeamMember> =>
  apiFetch(`/settings/team/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const resetTeamPassword = (id: number): Promise<{ ok: boolean; password: string }> =>
  apiFetch(`/settings/team/${id}/reset-password`, { method: "POST" });

export const deleteTeamMember = (id: number): Promise<void> =>
  apiFetch(`/settings/team/${id}`, { method: "DELETE" });
