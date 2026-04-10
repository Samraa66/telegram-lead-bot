import AppLayout from "@/components/AppLayout";
import MembersDashboard from "./MembersDashboard";

export default function MembersPage() {
  return (
    <AppLayout>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-foreground">Members</h2>
        <p className="text-sm text-muted-foreground mt-1">VIP depositors and activity tracking</p>
      </div>
      <MembersDashboard />
    </AppLayout>
  );
}
