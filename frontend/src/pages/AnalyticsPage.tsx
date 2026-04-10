import AppLayout from "@/components/AppLayout";
import AnalyticsDashboard from "./AnalyticsDashboard";

export default function AnalyticsPage() {
  return (
    <AppLayout>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-foreground">Analytics</h2>
        <p className="text-sm text-muted-foreground mt-1">Deposits, sources, and conversion metrics</p>
      </div>
      <AnalyticsDashboard />
    </AppLayout>
  );
}
