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
  target_stage: number;
  is_active: boolean;
}

export interface FollowUpTemplate {
  id: number;
  stage: number;
  sequence_num: number;
  message_text: string;
}

export interface QuickReply {
  id: number;
  stage_num: number;
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

export const createKeyword = (keyword: string, target_stage: number): Promise<Keyword> =>
  apiFetch("/settings/keywords", {
    method: "POST",
    body: JSON.stringify({ keyword, target_stage }),
  });

export const updateKeyword = (id: number, data: Partial<Omit<Keyword, "id">>): Promise<Keyword> =>
  apiFetch(`/settings/keywords/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

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

// ---- Quick Replies ----

export const fetchQuickReplies = (): Promise<QuickReply[]> =>
  apiFetch("/settings/quick-replies");

export const createQuickReply = (data: Omit<QuickReply, "id" | "is_active">): Promise<QuickReply> =>
  apiFetch("/settings/quick-replies", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const updateQuickReply = (id: number, data: Partial<Omit<QuickReply, "id">>): Promise<QuickReply> =>
  apiFetch(`/settings/quick-replies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteQuickReply = (id: number): Promise<void> =>
  apiFetch(`/settings/quick-replies/${id}`, { method: "DELETE" });

// ---- Stage Labels ----

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
