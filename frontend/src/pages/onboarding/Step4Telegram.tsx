import { useState } from "react";
import { StepBot, StepTelethon, StepChannel } from "./LegacyTelegramSteps";

interface Props { onNext: () => void; onBack: () => void; onSkip: () => void }

export default function Step4Telegram({ onNext, onBack, onSkip }: Props) {
  const [sub, setSub] = useState<0 | 1 | 2>(0);
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-bold text-foreground">Connect Telegram</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Three pieces: the bot that captures leads, the operator account that replies to them,
          and the channel where signals flow.
        </p>
      </div>
      {sub === 0 && <StepBot onDone={() => setSub(1)} onSkip={() => setSub(1)} />}
      {sub === 1 && <StepTelethon onDone={() => setSub(2)} onSkip={() => setSub(2)} />}
      {sub === 2 && <StepChannel onDone={onNext} onSkip={onNext} />}
      <div className="flex gap-2">
        <button onClick={onBack} className="px-3 h-9 rounded-lg border border-border text-xs hover:bg-secondary/40 transition-colors">Back</button>
        <button onClick={onSkip} className="flex-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
          Skip Telegram setup
        </button>
      </div>
    </div>
  );
}
