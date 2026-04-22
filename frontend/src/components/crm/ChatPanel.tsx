// DEPRECATED: ChatPanel is no longer used. Messaging happens natively in Telegram;
// the Telethon listener detects outgoing messages and advances stages automatically.
// Quick reply templates are handled by LeadDrawer. This file is kept for reference only.

import { Send, SkipForward, ChevronDown, AlertTriangle } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { Lead, Message, STAGE_ACTION_REPLIES, FOLLOWUP_REPLIES, STAGES, Stage, STAGE_COLORS, STAGE_TEXT_COLORS, ESCALATION_CONTACT_NAME, formatMessageTime, formatTimeInStage } from "../../data/crmData";
import { cn } from "../../lib/utils";

interface ChatPanelProps {
  lead: Lead;
  messages: Message[];
  onSendMessage: (text: string) => void;
  onNextLead?: () => void;
  onUpdateLead?: (updated: Lead) => void;
  onEscalate?: () => Promise<void>;
  flowInfo?: { waitingCount: number; nextLeadName: string; nextLeadTime: string } | null;
}

export function ChatPanel({ lead, messages, onSendMessage, onNextLead, onUpdateLead, onEscalate, flowInfo }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [stageToast, setStageToast] = useState<string | null>(null);
  const [showStageMenu, setShowStageMenu] = useState(false);
  const [escalated, setEscalated] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    setInput("");
  }, [lead.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const prevStageRef = useRef(lead.stage);
  useEffect(() => {
    if (prevStageRef.current !== lead.stage) {
      const idx = STAGES.indexOf(lead.stage);
      setStageToast(`Moved to Stage ${idx + 1} — ${lead.stage}`);
      prevStageRef.current = lead.stage;
      const t = setTimeout(() => setStageToast(null), 3000);
      return () => clearTimeout(t);
    }
  }, [lead.stage]);

  const handleSend = () => {
    if (!input.trim()) return;
    onSendMessage(input.trim());
    setInput("");
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const handleQuickReply = (text: string) => {
    onSendMessage(text);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (e.ctrlKey && onNextLead) {
        onNextLead();
      } else {
        handleSend();
      }
    }
  };

  const handleStageChange = (newStage: Stage) => {
    if (onUpdateLead && newStage !== lead.stage) {
      onUpdateLead({ ...lead, stage: newStage, stageEnteredAt: new Date().toISOString() });
    }
    setShowStageMenu(false);
  };

  const handleEscalate = async () => {
    if (onEscalate) await onEscalate();
    setEscalated(true);
  };

  const currentIdx = STAGES.indexOf(lead.stage);

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Flow indicator */}
      {flowInfo && flowInfo.waitingCount > 0 && (
        <div className="flex items-center justify-between px-4 py-1.5 bg-primary/10 border-b border-primary/20 text-xs">
          <span className="text-primary font-semibold">
            {flowInfo.waitingCount} waiting
          </span>
          <span className="text-muted-foreground">
            Next: <span className="text-foreground font-medium">{flowInfo.nextLeadName}</span>
            <span className="text-muted-foreground/70 ml-1">({flowInfo.nextLeadTime})</span>
          </span>
        </div>
      )}

      {/* Header - iOS style with stage change + escalate */}
      <div className="border-b border-border bg-card/80 backdrop-blur-xl">
        <div className="flex items-center gap-3 px-4 py-2.5">
          <div className="h-9 w-9 rounded-full bg-secondary flex items-center justify-center text-xs font-semibold text-foreground shrink-0">
            {lead.avatar}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground truncate leading-tight">{lead.name}</p>
            <p className="text-[11px] text-muted-foreground truncate">{lead.username} · Telegram</p>
          </div>
          {onNextLead && (
            <button
              onClick={onNextLead}
              className="h-8 px-3 rounded-full bg-primary text-primary-foreground flex items-center gap-1 text-xs font-bold shrink-0 active:scale-95 transition-transform"
            >
              Next
              <SkipForward className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Stage bar + Escalate */}
        <div className="flex items-center gap-2 px-4 pb-2">
          {/* Manual stage change button */}
          <div className="relative flex-1">
            <button
              onClick={() => setShowStageMenu(!showStageMenu)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-secondary active:bg-accent transition-colors w-full"
            >
              <span className={cn("h-2 w-2 rounded-full shrink-0", STAGE_COLORS[lead.stage])} />
              <span className={cn("text-[12px] font-semibold truncate", STAGE_TEXT_COLORS[lead.stage])}>
                Stage {currentIdx + 1} — {lead.stage}
              </span>
              <span className="text-[11px] text-muted-foreground ml-auto shrink-0">
                {formatTimeInStage(lead.stageEnteredAt)}
              </span>
              <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground shrink-0 transition-transform", showStageMenu && "rotate-180")} />
            </button>

            {/* Stage dropdown */}
            {showStageMenu && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border rounded-xl shadow-xl z-50 overflow-hidden">
                {STAGES.map((s, i) => (
                  <button
                    key={s}
                    onClick={() => handleStageChange(s)}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-2.5 text-left transition-colors",
                      s === lead.stage ? "bg-accent" : "active:bg-secondary",
                      i < STAGES.length - 1 && "border-b border-[hsl(var(--ios-separator))]"
                    )}
                  >
                    <span className={cn("h-2 w-2 rounded-full shrink-0", STAGE_COLORS[s])} />
                    <span className={cn("text-[13px] font-medium", s === lead.stage ? "text-foreground font-bold" : "text-muted-foreground")}>
                      Stage {i + 1} — {s}
                    </span>
                    {s === lead.stage && (
                      <span className="ml-auto text-primary text-xs font-bold">✓</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Escalate to Walid */}
          <button
            onClick={handleEscalate}
            disabled={escalated}
            className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-destructive/10 text-destructive text-[12px] font-bold active:bg-destructive/20 transition-colors shrink-0 disabled:opacity-50"
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{escalated ? "Escalated ✓" : `Escalate to ${ESCALATION_CONTACT_NAME}`}</span>
            <span className="sm:hidden">{escalated ? "Done ✓" : "Escalate"}</span>
          </button>
        </div>
      </div>

      {/* Stage toast */}
      {stageToast && (
        <div className="mx-4 mt-2 px-3 py-1.5 rounded-xl bg-primary/15 border border-primary/30 text-xs font-semibold text-primary text-center animate-in fade-in slide-in-from-top-2 duration-200">
          ✓ {stageToast}
        </div>
      )}

      {/* Close stage menu on tap outside */}
      {showStageMenu && (
        <div className="fixed inset-0 z-40" onClick={() => setShowStageMenu(false)} />
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-1.5">
        {messages.map((msg) => (
          <div key={msg.id} className={cn("flex", msg.sender === "operator" ? "justify-end" : "justify-start")}>
            <div
              className={cn(
                "max-w-[80%] px-3.5 py-2 text-[14px] leading-snug",
                msg.sender === "operator"
                  ? "bg-primary text-primary-foreground rounded-2xl rounded-br-md"
                  : "bg-card text-foreground rounded-2xl rounded-bl-md"
              )}
            >
              <p>{msg.text}</p>
              <p className={cn(
                "text-[10px] mt-0.5",
                msg.sender === "operator" ? "text-primary-foreground/50" : "text-muted-foreground/70"
              )}>
                {formatMessageTime(msg.timestamp)}
              </p>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Quick replies */}
      <div className="px-3 py-1.5 border-t border-border/50 space-y-1.5">
        <div className="flex gap-1.5 overflow-x-auto scrollbar-hide">
          {STAGE_ACTION_REPLIES.map((qr) => (
            <button
              key={qr}
              onClick={() => handleQuickReply(qr)}
              className="shrink-0 px-3 py-2 rounded-xl text-[12px] font-bold bg-primary/15 text-primary active:bg-primary/25 transition-colors whitespace-nowrap"
            >
              {qr}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5 overflow-x-auto scrollbar-hide">
          {FOLLOWUP_REPLIES.map((qr) => (
            <button
              key={qr}
              onClick={() => handleQuickReply(qr)}
              className="shrink-0 px-2.5 py-1.5 rounded-xl text-[12px] bg-secondary text-muted-foreground active:bg-accent transition-colors whitespace-nowrap"
            >
              {qr}
            </button>
          ))}
        </div>
      </div>

      {/* Input bar */}
      <div className="px-3 py-2 border-t border-border safe-bottom flex gap-2 items-center bg-card/80 backdrop-blur-xl">
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message..."
          className="flex-1 bg-secondary rounded-full px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-1 focus:ring-ring"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          className="h-10 w-10 rounded-full bg-primary text-primary-foreground flex items-center justify-center active:scale-95 transition-transform disabled:opacity-40 shrink-0"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
