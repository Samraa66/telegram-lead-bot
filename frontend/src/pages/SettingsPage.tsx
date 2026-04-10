import AppLayout from "@/components/AppLayout";
import { Settings } from "lucide-react";

export default function SettingsPage() {
  return (
    <AppLayout>
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-muted-foreground">
        <Settings className="w-10 h-10 opacity-30" />
        <p className="text-sm font-medium">Settings — Coming soon</p>
      </div>
    </AppLayout>
  );
}
