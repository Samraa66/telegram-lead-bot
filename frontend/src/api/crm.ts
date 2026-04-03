import { Lead, Message, backendStageToUi } from "../data/crmData";
import { getToken, clearAuth } from "./auth";
import { MOCK_LEADS } from "./mockData";

type ContactDto = {
  id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  current_stage: number;
  classification: string;
  notes: string;
  stage_entered_at: string | null;
  last_message_at: string | null;
  escalated: boolean | null;
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

function buildDisplayName(
  firstName: string | null,
  lastName: string | null,
  username: string | null,
  id: number,
): string {
  const full = [firstName, lastName].filter(Boolean).join(" ").trim();
  if (full) return full;
  const handle = (username || "").replace(/^@/, "").trim();
  if (handle) return handle;
  return `User ${id}`;
}

function avatarFor(displayName: string): string {
  const words = displayName.trim().split(/\s+/);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return displayName.slice(0, 2).toUpperCase() || "NA";
}

export async function fetchContacts(includeNoise = false): Promise<Lead[]> {
  if (import.meta.env.VITE_USE_MOCK === "true") {
    return includeNoise ? MOCK_LEADS : MOCK_LEADS.filter((l) => l.classification !== "noise");
  }
  const path = includeNoise ? "/contacts?include_noise=true" : "/contacts";
  const contacts = (await apiFetch(path)) as ContactDto[];
  return contacts.map((c) => {
    const username = c.username ? `@${String(c.username).replace(/^@/, "")}` : null;
    const lastTs = c.last_message_at || new Date().toISOString();
    const displayName = buildDisplayName(c.first_name, c.last_name, c.username, c.id);
    return {
      id: String(c.id),
      name: displayName,
      username: username ?? `@user_${c.id}`,
      stage: backendStageToUi(c.current_stage || 1),
      stageEnteredAt: c.stage_entered_at || lastTs,
      classification: c.classification || "new_lead",
      notes: c.notes || "",
      avatar: avatarFor(displayName),
      lastMessageAt: lastTs,
      unread: 0,
      escalated: c.escalated ?? false,
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
  if (import.meta.env.VITE_USE_MOCK === "true") return;
  await apiFetch("/send-message", {
    method: "POST",
    body: JSON.stringify({ contact_id: Number(contactId), message }),
  });
}

export async function setContactStage(contactId: string, stage: number): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK === "true") return;
  await apiFetch(`/contacts/${contactId}/stage`, {
    method: "POST",
    body: JSON.stringify({ stage }),
  });
}

export async function saveContactNotes(contactId: string, notes: string): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK === "true") return;
  await apiFetch(`/contacts/${contactId}/notes`, {
    method: "POST",
    body: JSON.stringify({ notes }),
  });
}

export async function escalateContact(contactId: string): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK === "true") return;
  await apiFetch(`/contacts/${contactId}/escalate`, {
    method: "POST",
  });
}

export async function toggleAffiliate(contactId: string): Promise<{ is_affiliate: boolean }> {
  if (import.meta.env.VITE_USE_MOCK === "true") return { is_affiliate: false };
  return apiFetch(`/contacts/${contactId}/affiliate`, { method: "POST" });
}

export async function markAsNoise(contactId: string): Promise<void> {
  if (import.meta.env.VITE_USE_MOCK === "true") return;
  await apiFetch(`/contacts/${contactId}/noise`, { method: "POST" });
}
