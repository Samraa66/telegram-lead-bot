import { useState, useCallback, useEffect } from "react";
import { LogOut } from "lucide-react";
import { LeadList } from "../components/crm/LeadList";
import { LeadDrawer } from "../components/crm/LeadDrawer";
import AnalyticsDashboard from "./AnalyticsDashboard";
import { Lead, uiStageToBackend } from "../data/crmData";
import {
  fetchContacts,
  sendMessageToContact,
  setContactStage,
  saveContactNotes,
  escalateContact,
  toggleAffiliate,
  markAsNoise,
} from "../api/crm";
import { clearAuth } from "../api/auth";

type Tab = "leads" | "analytics";

export default function CRMDashboard() {
  const [tab, setTab] = useState<Tab>("leads");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedLead = leads.find((l) => l.id === selectedLeadId) ?? null;

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

  // Poll for new contacts every 15 seconds
  useEffect(() => {
    const interval = setInterval(() => loadContacts(true), 15_000);
    return () => clearInterval(interval);
  }, [loadContacts]);

  const handleSelectLead = useCallback((id: string) => {
    setSelectedLeadId(id);
    setDrawerOpen(true);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setDrawerOpen(false);
  }, []);

  // Send a quick-reply template via Telethon (operator account)
  const handleSendTemplate = useCallback(async (text: string) => {
    if (!selectedLeadId) return;
    try {
      await sendMessageToContact(selectedLeadId, text);
      // Refresh to pick up any stage transition triggered by the template keyword
      await loadContacts(true);
    } catch (e: any) {
      setError(e?.message || "Failed to send template");
    }
  }, [selectedLeadId, loadContacts]);

  const handleUpdateLead = useCallback(async (updated: Lead) => {
    setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    try {
      await setContactStage(updated.id, uiStageToBackend(updated.stage));
      await loadContacts(true);
    } catch (e: any) {
      setError(e?.message || "Failed to update stage");
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

  const handleLogout = useCallback(() => {
    clearAuth();
    window.location.href = "/login";
  }, []);

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

  return (
    <div className="h-[100dvh] flex flex-col bg-[hsl(var(--ios-grouped-bg))]">
      {/* Error banner */}
      {error && (
        <div className="px-4 py-2 text-xs text-destructive bg-destructive/10 border-b border-destructive/20 text-center">
          {error}
        </div>
      )}

      {/* Top bar: tab toggle + logout */}
      <div className="safe-top bg-card/80 backdrop-blur-xl border-b border-[hsl(var(--ios-separator))] flex items-center justify-between px-4 pt-3 pb-2 z-20">
        <div className="flex gap-1 bg-secondary rounded-lg p-0.5">
          <button
            onClick={() => setTab("leads")}
            className={`px-4 py-1.5 rounded-md text-[13px] font-semibold transition-all ${
              tab === "leads"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground"
            }`}
          >
            Leads
          </button>
          <button
            onClick={() => setTab("analytics")}
            className={`px-4 py-1.5 rounded-md text-[13px] font-semibold transition-all ${
              tab === "analytics"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground"
            }`}
          >
            Analytics
          </button>
        </div>
        <button
          onClick={handleLogout}
          className="p-2 text-muted-foreground active:text-foreground transition-colors"
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 flex flex-col">
        {tab === "leads" ? (
          <LeadList
            leads={leads}
            selectedLeadId={selectedLeadId}
            onSelectLead={handleSelectLead}
          />
        ) : (
          <AnalyticsDashboard />
        )}
      </div>

      {/* Lead drawer */}
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
      />
    </div>
  );
}
