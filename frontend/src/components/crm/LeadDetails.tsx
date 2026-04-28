import { ChevronRight, AlertTriangle, StickyNote, Star, VolumeX } from "lucide-react";
import { useState, useEffect } from "react";
import { Lead, ESCALATION_CONTACT_NAME, formatTimeInStage, classificationLabel, classificationColor } from "../../data/crmData";
import { useWorkspaceStages } from "../../hooks/useWorkspaceStages";
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
  const pipeline = useWorkspaceStages();
  const [notes, setNotes] = useState(lead.notes);
  const [escalated, setEscalated] = useState(false);
  const storedUser = getStoredUser();
  const showAffiliateToggle = storedUser && canManageAffiliates(storedUser.role);

  const stages = pipeline?.stages || [];
  const currentStageObj = stages.find(s => s.id === lead.stageId);
  const currentIdx = currentStageObj ? stages.indexOf(currentStageObj) : -1;
  const stagePosition = lead.stagePosition ?? (currentIdx >= 0 ? currentIdx + 1 : 0);

  useEffect(() => {
    setNotes(lead.notes);
    setEscalated(false);
  }, [lead.id]);

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

  const saveNotes = async () => {
    await onSaveNotes(notes);
    onUpdateLead({ ...lead, notes });
  };

  const handleEscalate = async () => {
    await onEscalate();
    setEscalated(true);
  };

  const stageDotStyle: React.CSSProperties = currentStageObj?.color
    ? { backgroundColor: currentStageObj.color }
    : {};
  const stageTextStyle: React.CSSProperties = currentStageObj?.color
    ? { color: currentStageObj.color }
    : {};

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
            <span
              className="h-2.5 w-2.5 rounded-full bg-muted-foreground/40"
              style={stageDotStyle}
            />
            <span className="text-sm font-bold text-muted-foreground" style={stageTextStyle}>
              {stagePosition > 0 ? `Stage ${stagePosition} — ` : ""}{lead.stageName}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            In stage for <span className="text-foreground font-semibold">{formatTimeInStage(lead.stageEnteredAt)}</span>
          </p>
        </div>

        {/* Pipeline */}
        {stages.length > 0 && (
          <div className="ios-card p-4 space-y-2">
            <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Pipeline</p>
            <div className="flex items-center gap-1">
              {stages.map((s, i) => (
                <div key={s.id} className="flex-1">
                  <div
                    className={cn(
                      "h-2 rounded-full transition-colors",
                      i > currentIdx ? "bg-secondary" : ""
                    )}
                    style={i <= currentIdx && s.color ? { backgroundColor: s.color } : undefined}
                    title={s.name}
                  />
                </div>
              ))}
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>{stages[0]?.name ?? "Start"}</span>
              <span>{stages[stages.length - 1]?.name ?? "End"}</span>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="ios-card p-4 space-y-2.5">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Actions</p>
          <Button onClick={moveToNext} disabled={currentIdx < 0 || currentIdx >= stages.length - 1} className="w-full rounded-xl" size="sm">
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
            <Button size="sm" variant="secondary" onClick={saveNotes} className="w-full text-xs rounded-xl">
              Save Notes
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
