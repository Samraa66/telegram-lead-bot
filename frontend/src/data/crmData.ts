// Shared CRM frontend types + small helpers — pipeline stages are now dynamic
// and fetched via useWorkspaceStages(); see api/pipeline.ts.

export const ESCALATION_CONTACT_NAME = "Admin";

export type DepositStatus = "none" | "pending" | "deposited";

export interface Lead {
  id: string;
  name: string;
  username: string;
  stageId: number | null;
  stageName: string;
  stagePosition: number | null;
  stageEnteredAt: string;
  classification: string;
  notes: string;
  avatar: string;
  lastMessageAt: string;
  unread: number;
  escalated: boolean;
  depositStatus: DepositStatus;
  // Source attribution — populated by /start parser today, by Spec B's
  // invite-link claim flow once that ships. Both are nullable for now.
  sourceTag?: string | null;
  entryPath?: string | null;
}

export function classificationLabel(c: string): string {
  switch (c) {
    case "new_lead":   return "New";
    case "warm_lead":  return "Warm";
    case "vip":        return "VIP";
    case "affiliate":  return "Affiliate";
    case "noise":      return "Noise";
    default:           return c;
  }
}

export function classificationColor(c: string): string {
  switch (c) {
    case "new_lead":   return "bg-blue-500/15 text-blue-500";
    case "warm_lead":  return "bg-amber-500/15 text-amber-500";
    case "vip":        return "bg-emerald-500/15 text-emerald-500";
    case "affiliate":  return "bg-purple-500/15 text-purple-500";
    case "noise":      return "bg-gray-500/15 text-gray-500";
    default:           return "bg-gray-500/15 text-gray-500";
  }
}

export interface Message {
  id: string;
  leadId: string;
  text: string;
  sender: "client" | "operator";
  timestamp: string;
}

export const STAGE_ACTION_REPLIES = [
  "your link to open your free PuPrime account",
  "the hard part done",
  "exactly how to get set up",
  "welcome to the vip room",
  "really happy to have you here",
];

export const FOLLOWUP_REPLIES = [
  "any experience trading",
  "is there something specific holding you back",
  "Would you like to see some results?",
];

export const QUICK_REPLIES = [...STAGE_ACTION_REPLIES, ...FOLLOWUP_REPLIES];

export function formatTimeInStage(stageEnteredAt: string): string {
  const now = new Date();
  const diff = now.getTime() - new Date(stageEnteredAt).getTime();
  const mins = Math.max(0, Math.floor(diff / 60000));
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  const remHrs = hrs % 24;
  return remHrs > 0 ? `${days}d ${remHrs}h` : `${days}d`;
}

export function formatMessageTime(timestamp: string): string {
  const d = new Date(timestamp);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });
}

// Helper to look up the stage name from a fetched PipelineConfig given a stage_id
export function stageNameFromId(stages: { id: number; name: string }[] | undefined, id: number | null | undefined): string {
  if (!id || !stages) return "—";
  return stages.find(s => s.id === id)?.name ?? "—";
}
