import PipelineEditor from "../../components/pipeline/PipelineEditor";

interface Props { onNext: () => void; onBack: () => void; onSkip: () => void }

export default function Step3Pipeline({ onNext, onBack, onSkip }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Configure your pipeline</h2>
        <p className="text-sm text-muted-foreground mt-1">
          We seeded an 8-stage default. Rename, reorder, or delete anything you don't need.
          Pick which stage means "deposited" and "member" — those flags drive analytics.
        </p>
      </div>
      <PipelineEditor />
      <div className="flex gap-2">
        <button onClick={onBack} className="px-3 h-10 rounded-lg border border-border text-sm hover:bg-secondary/40 transition-colors">Back</button>
        <button onClick={onNext} className="flex-1 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold transition-colors hover:bg-primary/90">Continue</button>
      </div>
      <button onClick={onSkip} className="w-full text-xs text-muted-foreground hover:text-foreground transition-colors">
        Use defaults — set up later
      </button>
    </div>
  );
}
