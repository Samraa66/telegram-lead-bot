import { Lead, Message, backendStageToUi } from "../data/crmData";
import { getToken, clearAuth } from "./auth";

type ContactDto = {
  id: number;
  username: string | null;
  current_stage: number;
  classification: string;
  notes: string;
  stage_entered_at: string | null;
  last_message_at: string | null;
};

type MessageDto = {
  id: number;
  direction: "inbound" | "outbound" | null;
  content: string | null;
  sender: string | null;
  timestamp: string | null;
};

// In dev, call the local backend. In production, the frontend is served by the
// same FastAPI server so all API calls are same-origin (no host needed).
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
  if (res.status === 401) {
    clearAuth();
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.detail || data?.error || `Request failed (${res.status})`);
  }
  return data;
}

function avatarFor(username: string, id: string): string {
  const raw = (username || `u${id}`).replace(/^@/, "").trim();
  if (!raw) return "NA";
  return raw.slice(0, 2).toUpperCase();
}

function leadNameFromUsername(username: string | null, id: number): string {
  const base = (username || `user_${id}`).replace(/^@/, "").trim();
  return base || `User ${id}`;
}

export async function fetchContacts(includeNoise = false): Promise<Lead[]> {
  const path = includeNoise ? "/contacts?include_noise=true" : "/contacts";
  const contacts = (await apiFetch(path)) as ContactDto[];
  return contacts.map((c) => {
    const username = c.username ? `@${String(c.username).replace(/^@/, "")}` : `@user_${c.id}`;
    const lastTs = c.last_message_at || new Date().toISOString();
    return {
      id: String(c.id),
      name: leadNameFromUsername(c.username, c.id),
      username,
      stage: backendStageToUi(c.current_stage || 1),
      stageEnteredAt: c.stage_entered_at || lastTs,
      classification: c.classification || "new_lead",
      notes: c.notes || "",
      avatar: avatarFor(username, String(c.id)),
      lastMessageAt: lastTs,
      unread: 0,
    };
  });
}

export async function fetchContactMessages(contactId: string): Promise<Message[]> {
  const messages = (await apiFetch(`/contacts/${contactId}/messages`)) as MessageDto[];
  return messages.map((m) => ({
    id: String(m.id),
    leadId: String(contactId),
    text: m.content || "",
    sender: m.direction === "outbound" ? "operator" : "client",
    timestamp: m.timestamp || new Date().toISOString(),
  }));
}

export async function sendMessageToContact(contactId: string, message: string): Promise<void> {
  await apiFetch("/send-message", {
    method: "POST",
    body: JSON.stringify({ contact_id: Number(contactId), message }),
  });
}

export async function setContactStage(contactId: string, stage: number): Promise<void> {
  await apiFetch(`/contacts/${contactId}/stage`, {
    method: "POST",
    body: JSON.stringify({ stage }),
  });
}

export async function saveContactNotes(contactId: string, notes: string): Promise<void> {
  await apiFetch(`/contacts/${contactId}/notes`, {
    method: "POST",
    body: JSON.stringify({ notes }),
  });
}

export async function escalateContact(contactId: string): Promise<void> {
  await apiFetch(`/contacts/${contactId}/escalate`, {
    method: "POST",
  });
}

export async function toggleAffiliate(contactId: string): Promise<{ is_affiliate: boolean }> {
  return apiFetch(`/contacts/${contactId}/affiliate`, { method: "POST" });
}
