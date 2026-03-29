import { ChevronRight, AlertTriangle, StickyNote, Star, VolumeX } from "lucide-react";
import { useState, useEffect } from "react";
import { Lead, Stage, STAGES, STAGE_COLORS, STAGE_TEXT_COLORS, BUSINESS_OWNER_NAME, formatTimeInStage, classificationLabel, classificationColor } from "../../data/crmData";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { cn } from "../../lib/utils";
import { getStoredUser, canManageAffiliates } from "../../api/auth";

interface LeadDetailsProps {
  lead: Lead;
  onUpdateLead: (updated: Lead) => void;
  onSaveNotes: (notes: string) => Promise<void>;
  onEscalate: () => Promise<void>;
  onToggleAffiliate: () => Promise<void>;
  onMarkAsNoise: () => Promise<void>;
}

export function LeadDetails({ lead, onUpdateLead, onSaveNotes, onEscalate, onToggleAffiliate, onMarkAsNoise }: LeadDetailsProps) {
  const [notes, setNotes] = useState(lead.notes);
  const [escalated, setEscalated] = useState(false);
  const currentIdx = STAGES.indexOf(lead.stage);
  const storedUser = getStoredUser();
  const showAffiliateToggle = storedUser && canManageAffiliates(storedUser.role);

  useEffect(() => {
    setNotes(lead.notes);
    setEscalated(false);
  }, [lead.id]);

  const moveToNext = () => {
    if (currentIdx < STAGES.length - 1) {
      onUpdateLead({ ...lead, stage: STAGES[currentIdx + 1], stageEnteredAt: new Date().toISOString() });
    }
  };

  const handleStageOverride = (stage: Stage) => {
    if (stage !== lead.stage) {
      onUpdateLead({ ...lead, stage, stageEnteredAt: new Date().toISOString() });
    }
  };

  const saveNotes = async () => {
    await onSaveNotes(notes);
    onUpdateLead({ ...lead, notes });
  };

  const handleEscalate = async () => {
    await onEscalate();
    setEscalated(true);
  };

  return (
    <div className="flex flex-col h-full bg-[hsl(var(--ios-grouped-bg))] md:bg-card md:border-l md:border-border overflow-y-auto">
      <div className="p-5 space-y-4">
        {/* Lead info */}
        <div className="ios-card p-5 text-center">
          <div className="h-16 w-16 rounded-full bg-secondary flex items-center justify-center text-xl font-bold text-foreground mx-auto">
            {lead.avatar}
          </div>
          <h3 className="text-base font-bold text-foreground mt-3">{lead.name}</h3>
          <p className="text-xs text-muted-foreground">{lead.username}</p>
          <span className={cn("inline-block mt-2 px-2.5 py-0.5 rounded-full text-[11px] font-semibold", classificationColor(lead.classification))}>
            {classificationLabel(lead.classification)}
          </span>
        </div>

        {/* Current stage */}
        <div className="ios-card p-4 space-y-2">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Current Stage</p>
          <div className="flex items-center gap-2">
            <span className={cn("h-2.5 w-2.5 rounded-full", STAGE_COLORS[lead.stage])} />
            <span className={cn("text-sm font-bold", STAGE_TEXT_COLORS[lead.stage])}>
              Stage {currentIdx + 1} — {lead.stage}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            In stage for <span className="text-foreground font-semibold">{formatTimeInStage(lead.stageEnteredAt)}</span>
          </p>
        </div>

        {/* Pipeline */}
        <div className="ios-card p-4 space-y-2">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Pipeline</p>
          <div className="flex items-center gap-1">
            {STAGES.map((s, i) => (
              <div key={s} className="flex-1">
                <div
                  className={cn(
                    "h-2 rounded-full transition-colors",
                    i <= currentIdx ? STAGE_COLORS[s] : "bg-secondary"
                  )}
                  title={s}
                />
              </div>
            ))}
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground">
            <span>New</span>
            <span>VIP</span>
          </div>
        </div>

        {/* Actions */}
        <div className="ios-card p-4 space-y-2.5">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Actions</p>
          <Button onClick={moveToNext} disabled={currentIdx >= STAGES.length - 1} className="w-full rounded-xl" size="sm">
            <ChevronRight className="h-4 w-4 mr-1" />
            Move to {currentIdx < STAGES.length - 1 ? STAGES[currentIdx + 1] : "—"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={escalated}
            onClick={handleEscalate}
            className="w-full text-xs text-destructive hover:text-destructive rounded-xl"
          >
            <AlertTriangle className="h-3 w-3 mr-1" />
            {escalated ? `Escalated to ${BUSINESS_OWNER_NAME} ✓` : `Escalate to ${BUSINESS_OWNER_NAME}`}
          </Button>
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
                  ? "text-purple-600 border-purple-300 hover:text-purple-700"
                  : "text-muted-foreground"
              )}
            >
              <Star className="h-3 w-3 mr-1" />
              {lead.classification === "affiliate" ? "Remove Affiliate Tag" : "Mark as Affiliate"}
            </Button>
          )}
        </div>

        {/* Manual stage override */}
        <div className="ios-card p-4 space-y-2">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Override Stage</p>
          <div className="grid grid-cols-2 gap-1.5">
            {STAGES.map((s, i) => (
              <button
                key={s}
                onClick={() => handleStageOverride(s)}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-2 rounded-xl text-[11px] font-medium transition-colors text-left",
                  s === lead.stage
                    ? "bg-accent text-foreground font-bold ring-1 ring-primary/30"
                    : "bg-secondary text-muted-foreground active:bg-accent"
                )}
              >
                <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", STAGE_COLORS[s])} />
                <span className="truncate">{s}</span>
              </button>
            ))}
          </div>
        </div>

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
            <Button size="sm" variant="secondary" onClick={saveNotes} className="w-full text-xs rounded-xl">
              Save Notes
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
