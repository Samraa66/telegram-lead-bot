import AppLayout from "@/components/AppLayout";
import AffiliatesDashboard from "./AffiliatesDashboard";

export default function AffiliatesPage() {
  return (
    <AppLayout>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-foreground">Affiliates</h2>
        <p className="text-sm text-muted-foreground mt-1">Manage affiliate partners and commissions</p>
      </div>
      <AffiliatesDashboard />
    </AppLayout>
  );
}
