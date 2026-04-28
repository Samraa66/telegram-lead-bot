import { useState, useCallback, useEffect } from "react";
import AppLayout from "@/components/AppLayout";
import { LeadList } from "@/components/crm/LeadList";
import { LeadDrawer } from "@/components/crm/LeadDrawer";
import { Lead } from "@/data/crmData";
import {
  fetchContacts, sendMessageToContact, setContactStage,
  saveContactNotes, escalateContact, toggleAffiliate,
  markAsNoise, confirmDeposit,
} from "@/api/crm";

export default function LeadsPage() {
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
  useEffect(() => {
    const interval = setInterval(() => loadContacts(true), 15_000);
    return () => clearInterval(interval);
  }, [loadContacts]);

  const handleSelectLead = useCallback((id: string) => { setSelectedLeadId(id); setDrawerOpen(true); }, []);
  const handleCloseDrawer = useCallback(() => setDrawerOpen(false), []);

  const handleSendTemplate = useCallback(async (text: string) => {
    if (!selectedLeadId) return;
    try { await sendMessageToContact(selectedLeadId, text); await loadContacts(true); }
    catch (e: any) { setError(e?.message || "Failed to send template"); }
  }, [selectedLeadId, loadContacts]);

  const handleUpdateLead = useCallback(async (updated: Lead) => {
    setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    if (updated.stageId !== null) {
      try { await setContactStage(updated.id, updated.stageId); await loadContacts(true); }
      catch (e: any) { setError(e?.message || "Failed to update stage"); }
    }
  }, [loadContacts]);

  const handleSaveNotes = useCallback(async (notes: string) => {
    if (!selectedLeadId) return;
    try { await saveContactNotes(selectedLeadId, notes); }
    catch (e: any) { setError(e?.message || "Failed to save notes"); }
  }, [selectedLeadId]);

  const handleEscalate = useCallback(async () => {
    if (!selectedLeadId) return;
    try {
      await escalateContact(selectedLeadId);
      setLeads((prev) => prev.map((l) => (l.id === selectedLeadId ? { ...l, escalated: true } : l)));
    } catch (e: any) { setError(e?.message || "Failed to escalate"); }
  }, [selectedLeadId]);

  const handleMarkAsNoise = useCallback(async () => {
    if (!selectedLeadId) return;
    try { await markAsNoise(selectedLeadId); setDrawerOpen(false); await loadContacts(true); }
    catch (e: any) { setError(e?.message || "Failed to mark as noise"); }
  }, [selectedLeadId, loadContacts]);

  const handleToggleAffiliate = useCallback(async () => {
    if (!selectedLeadId) return;
    try { await toggleAffiliate(selectedLeadId); await loadContacts(true); }
    catch (e: any) { setError(e?.message || "Failed to update affiliate status"); }
  }, [selectedLeadId, loadContacts]);

  const handleConfirmDeposit = useCallback(async () => {
    if (!selectedLeadId) return;
    try { await confirmDeposit(selectedLeadId); setDrawerOpen(false); await loadContacts(true); }
    catch (e: any) { setError(e?.message || "Failed to confirm deposit"); }
  }, [selectedLeadId, loadContacts]);

  if (loading && leads.length === 0) {
    return (
      <AppLayout bare>
        <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">Loading leads…</div>
      </AppLayout>
    );
  }

  return (
    <AppLayout bare>
      {error && (
        <div className="px-4 py-2 text-xs text-destructive bg-destructive/10 border-b border-destructive/20 text-center">
          {error}
        </div>
      )}
      <div className="flex-1 min-h-0 flex flex-col">
        <LeadList leads={leads} selectedLeadId={selectedLeadId} onSelectLead={handleSelectLead} />
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
    </AppLayout>
  );
}
