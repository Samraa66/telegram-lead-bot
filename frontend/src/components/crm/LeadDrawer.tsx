import { X, ChevronRight, AlertTriangle, StickyNote, Star, VolumeX, MessageSquare, Zap } from "lucide-react";
import { useState, useEffect } from "react";
import { Lead, ESCALATION_CONTACT_NAME, formatTimeInStage, classificationLabel, classificationColor } from "../../data/crmData";
import { useWorkspaceStages } from "../../hooks/useWorkspaceStages";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { cn } from "../../lib/utils";
import { getStoredUser, canManageAffiliates } from "../../api/auth";

// Stage-contextual quick reply templates (keyed by stage position 1..n).
// Each text string MUST contain the keyword phrase that triggers stage detection
// in the backend pipeline (pipeline.py STAGE_KEYWORDS).
const STAGE_TEMPLATES: Record<number, { label: string; text: string }[]> = {
  1: [
    { label: "Qualify", text: "Hey! Quick question — do you have any experience trading, or is this something new for you? 😊" },
    { label: "Re-engage", text: "Hey, hope you're well! Just circling back — do you have any experience trading before?" },
  ],
  2: [
    { label: "Objection", text: "Totally understand! Is there something specific holding you back from getting started?" },
    { label: "Probe", text: "Makes sense. Is there something specific holding you back right now that I can help with?" },
  ],
  3: [
    { label: "Send link", text: "Here's your link to open your free PuPrime account — takes about 2 minutes! 👇" },
    { label: "Re-send link", text: "Sending over your link to open your free PuPrime account again in case you missed it 🔗" },
  ],
  4: [
    { label: "Confirm done", text: "Amazing — looks like you've got the hard part done! 🎉 Let me know once you're in and I'll sort your access." },
    { label: "Check in", text: "Hey! Just checking in — is the hard part done with the account setup? Happy to help if you're stuck!" },
  ],
  5: [
    { label: "Setup guide", text: "Perfect! Let me walk you through exactly how to get set up with the signals 📊" },
    { label: "Next steps", text: "Great news! I'll show you exactly how to get set up from here — just follow these steps 👇" },
  ],
  6: [
    { label: "VIP access", text: "Welcome to the VIP room! You're officially in 🔥 Here's everything you need to know to get started..." },
    { label: "VIP entry", text: "Welcome to the vip room — so pumped to have you here! Let's get you fully set up 🚀" },
  ],
  7: [
    { label: "Welcome", text: "Really happy to have you here with us! Here's what to expect going forward 🙌" },
    { label: "Onboard", text: "I'm really happy to have you here — let's make sure you're getting the most out of everything!" },
  ],
};

interface LeadDrawerProps {
  lead: Lead | null;
  isOpen: boolean;
  onClose: () => void;
  onSendTemplate: (text: string) => Promise<void>;
  onUpdateLead: (updated: Lead) => void;
  onSaveNotes: (notes: string) => Promise<void>;
  onEscalate: () => Promise<void>;
  onMarkAsNoise: () => Promise<void>;
  onToggleAffiliate: () => Promise<void>;
  onConfirmDeposit: () => Promise<void>;
}

export function LeadDrawer({
  lead,
  isOpen,
  onClose,
  onSendTemplate,
  onUpdateLead,
  onSaveNotes,
  onEscalate,
  onMarkAsNoise,
  onToggleAffiliate,
  onConfirmDeposit,
}: LeadDrawerProps) {
  const pipeline = useWorkspaceStages();
  const [notes, setNotes] = useState(lead?.notes ?? "");
  const [escalated, setEscalated] = useState(false);
  const [sendingTemplate, setSendingTemplate] = useState<string | null>(null);
  const [sentTemplate, setSentTemplate] = useState<string | null>(null);
  const [depositConfirmed, setDepositConfirmed] = useState(false);

  const storedUser = getStoredUser();
  const showAffiliateToggle = storedUser && canManageAffiliates(storedUser.role);

  useEffect(() => {
    if (lead) {
      setNotes(lead.notes);
      setEscalated(lead.escalated);
      setSentTemplate(null);
    }
  }, [lead?.id]);

  if (!lead) return null;

  const stages = pipeline?.stages || [];
  const currentStageObj = stages.find(s => s.id === lead.stageId);
  const currentIdx = currentStageObj ? stages.indexOf(currentStageObj) : -1;
  const stagePosition = lead.stagePosition ?? (currentIdx + 1);
  const templates = STAGE_TEMPLATES[stagePosition] ?? [];

  const handleStageOverride = (stageId: number) => {
    if (stageId !== lead.stageId) {
      const s = stages.find(st => st.id === stageId);
      onUpdateLead({
        ...lead,
        stageId,
        stageName: s?.name ?? "—",
        stagePosition: s?.position ?? null,
        stageEnteredAt: new Date().toISOString(),
      });
    }
  };

  const moveToNext = () => {
    if (currentIdx >= 0 && currentIdx < stages.length - 1) {
      const nextStage = stages[currentIdx + 1];
      onUpdateLead({
        ...lead,
        stageId: nextStage.id,
        stageName: nextStage.name,
        stagePosition: nextStage.position,
        stageEnteredAt: new Date().toISOString(),
      });
    }
  };

  const handleSaveNotes = async () => {
    await onSaveNotes(notes);
    onUpdateLead({ ...lead, notes });
  };

  const handleEscalate = async () => {
    await onEscalate();
    setEscalated(true);
  };

  const handleSendTemplate = async (text: string) => {
    setSendingTemplate(text);
    try {
      await onSendTemplate(text);
      setSentTemplate(text);
      setTimeout(() => setSentTemplate(null), 3000);
    } finally {
      setSendingTemplate(null);
    }
  };

  // Stage dot color from API
  const stageDotStyle: React.CSSProperties = currentStageObj?.color
    ? { backgroundColor: currentStageObj.color }
    : {};
  const stageTextStyle: React.CSSProperties = currentStageObj?.color
    ? { color: currentStageObj.color }
    : {};

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          "fixed inset-0 bg-black/50 z-40 transition-opacity duration-300",
          isOpen ? "opacity-100" : "opacity-0 pointer-events-none"
        )}
        onClick={onClose}
      />

      {/* Drawer panel — bottom sheet on mobile, right panel on desktop */}
      <div
        className={cn(
          "fixed z-50 bg-[hsl(var(--ios-grouped-bg))] overflow-y-auto transition-transform duration-300 ease-in-out",
          // Mobile: slide up from bottom
          "inset-x-0 bottom-0 rounded-t-2xl max-h-[92vh]",
          // Desktop: slide in from right
          "md:inset-x-auto md:right-0 md:top-0 md:bottom-0 md:w-96 md:rounded-none md:rounded-l-2xl md:max-h-none",
          isOpen
            ? "translate-y-0 md:translate-y-0 md:translate-x-0"
            : "translate-y-full md:translate-y-0 md:translate-x-full"
        )}
      >
        {/* Drag handle (mobile only) */}
        <div className="md:hidden flex justify-center pt-3 pb-1">
          <div className="h-1 w-10 rounded-full bg-muted-foreground/30" />
        </div>

        {/* Header */}
        <div className="sticky top-0 bg-[hsl(var(--ios-grouped-bg))]/95 backdrop-blur-sm z-10 px-4 pt-2 pb-3 flex items-center justify-between border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <div className="h-9 w-9 rounded-full bg-secondary flex items-center justify-center text-sm font-bold text-foreground shrink-0">
                {lead.avatar}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-bold text-foreground truncate">{lead.name}</p>
                <p className="text-xs text-muted-foreground truncate">{lead.username}</p>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-muted-foreground active:text-foreground transition-colors shrink-0 ml-2"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-4 space-y-4 pb-safe-bottom">

          {/* Stage info */}
          <div className="ios-card p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Current Stage</p>
              <span className="text-xs text-muted-foreground font-semibold tabular-nums">
                {formatTimeInStage(lead.stageEnteredAt)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full shrink-0 bg-muted-foreground/40"
                style={stageDotStyle}
              />
              <span className="text-sm font-bold text-muted-foreground" style={stageTextStyle}>
                {stagePosition > 0 ? `${stagePosition} — ` : ""}{lead.stageName}
              </span>
            </div>
            {/* Pipeline bar */}
            {stages.length > 0 && (
              <div className="flex items-center gap-0.5 mt-1">
                {stages.map((s, i) => (
                  <div key={s.id} className="flex-1">
                    <div
                      className={cn("h-1.5 rounded-full", i <= currentIdx ? "" : "bg-secondary")}
                      style={i <= currentIdx && s.color ? { backgroundColor: s.color } : undefined}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Quick Reply Templates */}
          {templates.length > 0 && (
            <div className="ios-card p-4 space-y-2.5">
              <div className="flex items-center gap-1.5">
                <Zap className="h-3.5 w-3.5 text-primary" />
                <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Quick Replies</p>
              </div>
              <p className="text-[11px] text-muted-foreground -mt-1">
                Sends via Telegram — stage advances automatically on keyword match
              </p>
              <div className="space-y-2">
                {templates.map((t) => (
                  <button
                    key={t.label}
                    onClick={() => handleSendTemplate(t.text)}
                    disabled={sendingTemplate !== null}
                    className={cn(
                      "w-full text-left px-3 py-2.5 rounded-xl border transition-all text-sm",
                      sentTemplate === t.text
                        ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                        : "bg-secondary border-transparent text-foreground active:bg-accent",
                      sendingTemplate === t.text && "opacity-60"
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <MessageSquare className="h-3.5 w-3.5 mt-0.5 shrink-0 text-primary" />
                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold text-primary mb-0.5">{t.label}</p>
                        <p className="text-[12px] text-muted-foreground leading-relaxed line-clamp-2">{t.text}</p>
                      </div>
                    </div>
                    {sentTemplate === t.text && (
                      <p className="text-[11px] text-emerald-400 mt-1 font-semibold">Sent ✓</p>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="ios-card p-4 space-y-2.5">
            <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Actions</p>
            <Button
              onClick={moveToNext}
              disabled={currentIdx < 0 || currentIdx >= stages.length - 1}
              className="w-full rounded-xl"
              size="sm"
            >
              <ChevronRight className="h-4 w-4 mr-1" />
              Move to {currentIdx >= 0 && currentIdx < stages.length - 1 ? stages[currentIdx + 1].name : "—"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={escalated}
              onClick={handleEscalate}
              className="w-full text-xs text-destructive hover:text-destructive rounded-xl"
            >
              <AlertTriangle className="h-3 w-3 mr-1" />
              {escalated ? `Escalated to ${ESCALATION_CONTACT_NAME} ✓` : `Escalate to ${ESCALATION_CONTACT_NAME}`}
            </Button>
            {!depositConfirmed && lead.depositStatus !== "deposited" && lead.classification !== "noise" && (
              <Button
                variant="outline"
                size="sm"
                onClick={async () => { await onConfirmDeposit(); setDepositConfirmed(true); }}
                className="w-full text-xs text-stage-qualified border-stage-qualified/30 rounded-xl"
              >
                <Star className="h-3 w-3 mr-1" />
                Confirm Deposit → VIP
              </Button>
            )}
            {(depositConfirmed || lead.depositStatus === "deposited") && (
              <p className="text-center text-[11px] text-stage-qualified font-semibold">Deposit confirmed ✓ — moved to Members</p>
            )}
            {lead.classification !== "noise" && (
              <Button
                variant="outline"
                size="sm"
                onClick={onMarkAsNoise}
                className="w-full text-xs text-muted-foreground rounded-xl"
              >
                <VolumeX className="h-3 w-3 mr-1" />
                Mark as Noise
              </Button>
            )}
            {showAffiliateToggle && (
              <Button
                variant="outline"
                size="sm"
                onClick={onToggleAffiliate}
                className={cn(
                  "w-full text-xs rounded-xl",
                  lead.classification === "affiliate"
                    ? "text-purple-500 border-purple-400/40"
                    : "text-muted-foreground"
                )}
              >
                <Star className="h-3 w-3 mr-1" />
                {lead.classification === "affiliate" ? "Remove Affiliate Tag" : "Mark as Affiliate"}
              </Button>
            )}
          </div>

          {/* Manual stage override */}
          {stages.length > 0 && (
            <div className="ios-card p-4 space-y-2">
              <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Override Stage</p>
              <div className="grid grid-cols-2 gap-1.5">
                {stages.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => handleStageOverride(s.id)}
                    className={cn(
                      "flex items-center gap-1.5 px-2.5 py-2 rounded-xl text-[11px] font-medium transition-colors text-left",
                      s.id === lead.stageId
                        ? "bg-accent text-foreground font-bold ring-1 ring-primary/30"
                        : "bg-secondary text-muted-foreground active:bg-accent"
                    )}
                  >
                    <span
                      className="h-1.5 w-1.5 rounded-full shrink-0 bg-muted-foreground/40"
                      style={s.color ? { backgroundColor: s.color } : undefined}
                    />
                    <span className="truncate">{s.name}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Notes */}
          <div className="ios-card p-4 space-y-2">
            <div className="flex items-center gap-1.5">
              <StickyNote className="h-3.5 w-3.5 text-muted-foreground" />
              <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Notes</p>
            </div>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes about this lead..."
              className="min-h-[80px] bg-secondary border-none text-sm resize-none rounded-xl"
            />
            {notes !== lead.notes && (
              <Button size="sm" variant="secondary" onClick={handleSaveNotes} className="w-full text-xs rounded-xl">
                Save Notes
              </Button>
            )}
          </div>

          {/* Classification */}
          <div className="ios-card p-4 space-y-2">
            <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Classification</p>
            <div className="flex items-center gap-2 flex-wrap">
              <span className={cn("px-2.5 py-0.5 rounded-full text-[11px] font-semibold", classificationColor(lead.classification))}>
                {classificationLabel(lead.classification)}
              </span>
              {lead.depositStatus === "deposited" && (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-500">
                  Deposited
                </span>
              )}
            </div>
          </div>

        </div>
      </div>
    </>
  );
}
