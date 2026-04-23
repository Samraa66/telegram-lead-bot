// Shared CRM frontend types + constants (no mock in-memory leads/messages).

export const ESCALATION_CONTACT_NAME = "Admin";

export type Stage =
  | "New Lead"
  | "Qualified"
  | "Hesitant / Ghosting"
  | "Link Sent"
  | "Account Created"
  | "Deposit Intent"
  | "Deposited"
  | "VIP Member";

export const STAGES: Stage[] = [
  "New Lead",
  "Qualified",
  "Hesitant / Ghosting",
  "Link Sent",
  "Account Created",
  "Deposit Intent",
  "Deposited",
  "VIP Member",
];

export const STAGE_COLORS: Record<Stage, string> = {
  "New Lead": "bg-stage-new",
  Qualified: "bg-stage-qualified",
  "Hesitant / Ghosting": "bg-stage-hesitant",
  "Link Sent": "bg-stage-link-sent",
  "Account Created": "bg-stage-link-sent",
  "Deposit Intent": "bg-stage-link-sent",
  Deposited: "bg-stage-deposited",
  "VIP Member": "bg-stage-deposited",
};

export const STAGE_TEXT_COLORS: Record<Stage, string> = {
  "New Lead": "text-stage-new",
  Qualified: "text-stage-qualified",
  "Hesitant / Ghosting": "text-stage-hesitant",
  "Link Sent": "text-stage-link-sent",
  "Account Created": "text-stage-link-sent",
  "Deposit Intent": "text-stage-link-sent",
  Deposited: "text-stage-deposited",
  "VIP Member": "text-stage-deposited",
};

export interface Lead {
  id: string;
  name: string;
  username: string;
  stage: Stage;
  stageEnteredAt: string;
  classification: string;
  notes: string;
  avatar: string;
  lastMessageAt: string;
  unread: number;
  escalated: boolean;
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

// Backend stage mapping (1..8) -> UI labels
export function backendStageToUi(stageNum: number): Stage {
  switch (stageNum) {
    case 1:
      return "New Lead";
    case 2:
      return "Qualified";
    case 3:
      return "Hesitant / Ghosting";
    case 4:
      return "Link Sent";
    case 5:
      return "Account Created";
    case 6:
      return "Deposit Intent";
    case 7:
      return "Deposited";
    case 8:
      return "VIP Member";
    default:
      return "New Lead";
  }
}

export function uiStageToBackend(stage: Stage): number {
  switch (stage) {
    case "New Lead":
      return 1;
    case "Qualified":
      return 2;
    case "Hesitant / Ghosting":
      return 3;
    case "Link Sent":
      return 4;
    case "Account Created":
      return 5;
    case "Deposit Intent":
      return 6;
    case "Deposited":
      return 7;
    case "VIP Member":
      return 8;
    default:
      return 1;
  }
}
