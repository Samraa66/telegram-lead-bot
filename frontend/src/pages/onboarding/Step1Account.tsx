import { Check } from "lucide-react";

interface Props {
  user: { username: string; role: string; workspace_id: number } | null;
  onNext: () => void;
}

export default function Step1Account({ user, onNext }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-foreground">Account confirmed</h2>
        <p className="text-sm text-muted-foreground mt-1">
          You're signed in. Let's set up the rest of your workspace.
        </p>
      </div>
      <div className="rounded-lg bg-secondary/40 border border-border p-4 space-y-2">
        <p className="text-[11px] text-muted-foreground uppercase tracking-wider">Signed in as</p>
        <p className="text-sm font-medium text-foreground">{user?.username || "—"}</p>
        <div className="flex items-center gap-1 text-xs text-emerald-500">
          <Check className="h-3.5 w-3.5" />
          {user?.role} · workspace {user?.workspace_id}
        </div>
      </div>
      <button
        onClick={onNext}
        className="w-full h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold transition-colors hover:bg-primary/90">
        Continue
      </button>
    </div>
  );
}
