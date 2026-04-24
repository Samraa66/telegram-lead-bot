import { useEffect, useState } from "react";
import { Users, DollarSign, UserPlus, Star } from "lucide-react";
import AppLayout from "@/components/AppLayout";
import KpiCard from "@/components/KpiCard";
import PipelinePreview from "@/components/PipelinePreview";
import RecentLeads from "@/components/RecentLeads";
import DepositsChart from "@/components/DepositsChart";
import WorkspaceHealthCard from "@/components/WorkspaceHealthCard";
import { fetchOverview, Overview } from "@/api/analytics";
import { fetchAffiliatePerformance } from "@/api/affiliates";
import { fetchMembers } from "@/api/members";
import { getStoredUser } from "@/api/auth";
import AffiliateSelfDashboard from "./AffiliateSelfDashboard";

const Dashboard = () => {
  const user = getStoredUser();
  if (user?.role === "affiliate") {
    return (
      <AppLayout>
        <AffiliateSelfDashboard />
      </AppLayout>
    );
  }
  const [overview, setOverview] = useState<Overview | null>(null);
  const [affiliateCount, setAffiliateCount] = useState<number | null>(null);
  const [memberCount, setMemberCount] = useState<number | null>(null);

  useEffect(() => {
    fetchOverview(null).then(setOverview).catch(() => {});
    fetchAffiliatePerformance().then((a) => setAffiliateCount(a.length)).catch(() => {});
    fetchMembers().then((m) => setMemberCount(m.length)).catch(() => {});
  }, []);

  const fmt = (n: number | undefined) =>
    n == null ? "—" : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);

  const fmtUSD = (n: number | undefined) =>
    n == null ? "—" : `$${n.toLocaleString()}`;

  return (
    <AppLayout>
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-foreground">Dashboard</h2>
        <p className="text-sm text-muted-foreground mt-1">Welcome back — here's your overview</p>
      </div>

      <div className="mb-6">
        <WorkspaceHealthCard />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <KpiCard
          title="Total Leads"
          value={fmt(overview?.total_leads)}
          change={overview ? `+${overview.new_this_week} this week` : undefined}
          changeType={overview && overview.new_this_week > 0 ? "positive" : "neutral"}
          icon={Users}
        />
        <KpiCard
          title="Total Deposited"
          value={fmtUSD(overview?.total_deposited)}
          change={overview ? `${overview.overall_conversion.toFixed(1)}% conversion rate` : undefined}
          changeType="neutral"
          icon={DollarSign}
        />
        <KpiCard
          title="Active Affiliates"
          value={affiliateCount != null ? String(affiliateCount) : "—"}
          icon={UserPlus}
        />
        <KpiCard
          title="VIP Members"
          value={memberCount != null ? String(memberCount) : "—"}
          icon={Star}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <DepositsChart />
        <PipelinePreview />
      </div>

      <RecentLeads />
    </AppLayout>
  );
};

export default Dashboard;
