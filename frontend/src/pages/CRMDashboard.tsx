import { useState, useCallback, useEffect, useRef } from "react";
import {
  LogOut,
  Users,
  BarChart2,
  Star,
  Link2,
  ChevronUp,
  Menu,
} from "lucide-react";
import { LeadList } from "../components/crm/LeadList";
import { LeadDrawer } from "../components/crm/LeadDrawer";
import AnalyticsDashboard from "./AnalyticsDashboard";
import MembersDashboard from "./MembersDashboard";
import AffiliatesDashboard from "./AffiliatesDashboard";
import { Lead } from "../data/crmData";
import {
  fetchContacts,
  sendMessageToContact,
  setContactStage,
  saveContactNotes,
  escalateContact,
  toggleAffiliate,
  markAsNoise,
  confirmDeposit,
} from "../api/crm";
import { clearAuth, getStoredUser } from "../api/auth";

type Tab = "leads" | "analytics" | "members" | "affiliates";

const NAV_ITEMS = [
  { id: "leads" as Tab, label: "Leads", icon: Users, roles: null },
  { id: "analytics" as Tab, label: "Analytics", icon: BarChart2, roles: null },
  { id: "members" as Tab, label: "Members", icon: Star, roles: ["developer", "admin", "vip_manager"] },
  { id: "affiliates" as Tab, label: "Affiliates", icon: Link2, roles: ["developer", "admin"] },
];

export default function CRMDashboard() {
  const storedUser = getStoredUser();
  const role = storedUser?.role || "";
  const isVipManager = role === "vip_manager";

  const visibleNav = NAV_ITEMS.filter((item) => {
    if (isVipManager && (item.id === "leads" || item.id === "analytics")) return false;
    if (item.roles && !item.roles.includes(role)) return false;
    return true;
  });

  const [tab, setTab] = useState<Tab>(isVipManager ? "members" : "leads");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  const selectedLead = leads.find((l) => l.id === selectedLeadId) ?? null;

  // Close user menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const loadContacts = useCallback(async (silent = false) => {
    if (!silent) { setLoading(true); setError(null); }
    try {
      const contacts = await fetchContacts(true);
      setLeads(contacts);
    } catch (e: any) {
      if (!silent) setError(e?.message || "Failed to load contacts");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { loadContacts(); }, [loadContacts]);

  useEffect(() => {
    const interval = setInterval(() => loadContacts(true), 15_000);
    return () => clearInterval(interval);
  }, [loadContacts]);

  const handleSelectLead = useCallback((id: string) => {
    setSelectedLeadId(id);
    setDrawerOpen(true);
  }, []);

  const handleCloseDrawer = useCallback(() => setDrawerOpen(false), []);

  const handleSendTemplate = useCallback(async (text: string) => {
    if (!selectedLeadId) return;
    try {
      await sendMessageToContact(selectedLeadId, text);
      await loadContacts(true);
    } catch (e: any) {
      setError(e?.message || "Failed to send template");
    }
  }, [selectedLeadId, loadContacts]);

  const handleUpdateLead = useCallback(async (updated: Lead) => {
    setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    if (updated.stageId !== null) {
      try {
        await setContactStage(updated.id, updated.stageId);
        await loadContacts(true);
      } catch (e: any) {
        setError(e?.message || "Failed to update stage");
      }
    }
  }, [loadContacts]);

  const handleSaveNotes = useCallback(async (notes: string) => {
    if (!selectedLeadId) return;
    try {
      await saveContactNotes(selectedLeadId, notes);
    } catch (e: any) {
      setError(e?.message || "Failed to save notes");
    }
  }, [selectedLeadId]);

  const handleEscalate = useCallback(async () => {
    if (!selectedLeadId) return;
    try {
      await escalateContact(selectedLeadId);
      setLeads((prev) =>
        prev.map((l) => (l.id === selectedLeadId ? { ...l, escalated: true } : l))
      );
    } catch (e: any) {
      setError(e?.message || "Failed to escalate");
    }
  }, [selectedLeadId]);

  const handleMarkAsNoise = useCallback(async () => {
    if (!selectedLeadId) return;
    try {
      await markAsNoise(selectedLeadId);
      setDrawerOpen(false);
      await loadContacts(true);
    } catch (e: any) {
      setError(e?.message || "Failed to mark as noise");
    }
  }, [selectedLeadId, loadContacts]);

  const handleToggleAffiliate = useCallback(async () => {
    if (!selectedLeadId) return;
    try {
      await toggleAffiliate(selectedLeadId);
      await loadContacts(true);
    } catch (e: any) {
      setError(e?.message || "Failed to update affiliate status");
    }
  }, [selectedLeadId, loadContacts]);

  const handleConfirmDeposit = useCallback(async () => {
    if (!selectedLeadId) return;
    try {
      await confirmDeposit(selectedLeadId);
      setDrawerOpen(false);
      await loadContacts(true);
    } catch (e: any) {
      setError(e?.message || "Failed to confirm deposit");
    }
  }, [selectedLeadId, loadContacts]);

  const handleLogout = useCallback(() => {
    clearAuth();
    window.location.href = "/login";
  }, []);

  const handleNavClick = (id: Tab) => {
    setTab(id);
    setSidebarOpen(false);
  };

  if (loading && leads.length === 0) {
    return (
      <div className="h-screen flex items-center justify-center text-muted-foreground">
        Loading CRM...
      </div>
    );
  }

  if (error && leads.length === 0) {
    return (
      <div className="h-screen flex items-center justify-center text-destructive">
        {error}
      </div>
    );
  }

  const initials = (storedUser?.username || "U").slice(0, 2).toUpperCase();

  const Sidebar = ({ mobile }: { mobile?: boolean }) => (
    <aside
      className={
        mobile
          ? "flex flex-col h-full"
          : "hidden md:flex flex-col w-56 flex-shrink-0 border-r border-[hsl(var(--sidebar-border))]"
      }
      style={{ background: "hsl(var(--sidebar-background))" }}
    >
      {/* Logo */}
      <div className="px-4 py-5 border-b border-[hsl(var(--sidebar-border))]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
            <span className="text-[hsl(var(--primary-foreground))] font-bold text-sm">T</span>
          </div>
          <div>
            <div className="text-sm font-semibold text-foreground leading-none">Telelytics</div>
            <div className="text-[11px] text-muted-foreground mt-0.5">Affiliate Manager</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
        {visibleNav.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => handleNavClick(id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all text-left ${
              tab === id
                ? "bg-primary/15 text-primary"
                : "text-[hsl(var(--sidebar-foreground))] hover:bg-[hsl(var(--sidebar-accent))] hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4 flex-shrink-0" />
            {label}
          </button>
        ))}
      </nav>

      {/* User section */}
      <div className="p-3 border-t border-[hsl(var(--sidebar-border))] relative" ref={mobile ? undefined : userMenuRef}>
        <button
          onClick={() => setUserMenuOpen((v) => !v)}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[hsl(var(--sidebar-accent))] transition-all"
        >
          <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
            <span className="text-primary text-xs font-bold">{initials}</span>
          </div>
          <div className="flex-1 text-left min-w-0">
            <div className="text-xs font-medium text-foreground truncate">
              {storedUser?.username || "User"}
            </div>
            <div className="text-[11px] text-muted-foreground capitalize">{role}</div>
          </div>
          <ChevronUp
            className={`h-3 w-3 text-muted-foreground transition-transform ${
              userMenuOpen ? "" : "rotate-180"
            }`}
          />
        </button>

        {userMenuOpen && (
          <div className="absolute bottom-full left-3 right-3 mb-1 bg-card border border-border rounded-lg shadow-xl overflow-hidden z-50">
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-destructive hover:bg-destructive/10 transition-colors"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );

  return (
    <div className="h-[100dvh] flex bg-[hsl(var(--ios-grouped-bg))]">
      {/* Desktop sidebar */}
      <Sidebar />

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 flex"
          onClick={() => setSidebarOpen(false)}
        >
          <div className="absolute inset-0 bg-black/60" />
          <div
            className="relative w-56 h-full z-50"
            onClick={(e) => e.stopPropagation()}
          >
            <div ref={userMenuRef} className="h-full">
              <Sidebar mobile />
            </div>
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center px-4 py-3 bg-card/80 backdrop-blur-xl border-b border-[hsl(var(--ios-separator))]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 text-muted-foreground"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="ml-3 text-sm font-semibold text-foreground capitalize">{tab}</span>
        </div>

        {error && (
          <div className="px-4 py-2 text-xs text-destructive bg-destructive/10 border-b border-destructive/20 text-center">
            {error}
          </div>
        )}

        <div className="flex-1 min-h-0 flex flex-col">
          {tab === "leads" && (
            <LeadList
              leads={leads}
              selectedLeadId={selectedLeadId}
              onSelectLead={handleSelectLead}
            />
          )}
          {tab === "analytics" && <AnalyticsDashboard />}
          {tab === "members" && <MembersDashboard />}
          {tab === "affiliates" && <AffiliatesDashboard />}
        </div>
      </div>

      <LeadDrawer
        lead={selectedLead}
        isOpen={drawerOpen}
        onClose={handleCloseDrawer}
        onSendTemplate={handleSendTemplate}
        onUpdateLead={handleUpdateLead}
        onSaveNotes={handleSaveNotes}
        onEscalate={handleEscalate}
        onMarkAsNoise={handleMarkAsNoise}
        onToggleAffiliate={handleToggleAffiliate}
        onConfirmDeposit={handleConfirmDeposit}
      />
    </div>
  );
}
