import { useState, useCallback, useEffect } from "react";
import { ArrowLeft, PanelRightOpen, LogOut } from "lucide-react";
import { LeadList } from "../components/crm/LeadList";
import { ChatPanel } from "../components/crm/ChatPanel";
import { LeadDetails } from "../components/crm/LeadDetails";
import { Lead, Message, formatTimeInStage, uiStageToBackend } from "../data/crmData";
import { useIsMobile } from "../hooks/use-mobile";
import { fetchContacts, fetchContactMessages, sendMessageToContact, setContactStage, saveContactNotes, escalateContact, toggleAffiliate, markAsNoise } from "../api/crm";
import { clearAuth } from "../api/auth";

type MobileView = "list" | "chat" | "details";

export default function CRMDashboard() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [allMessages, setAllMessages] = useState<Message[]>([]);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [showDetails] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isMobile = useIsMobile();
  const [mobileView, setMobileView] = useState<MobileView>("list");

  const selectedLead = leads.find((l) => l.id === selectedLeadId) ?? null;
  const leadMessages = selectedLeadId ? allMessages.filter((m) => m.leadId === selectedLeadId) : [];

  const sortedLeads = [...leads].sort(
    (a, b) => new Date(a.stageEnteredAt).getTime() - new Date(b.stageEnteredAt).getTime(),
  );

  const loadContacts = useCallback(async (silent = false) => {
    if (!silent) { setLoading(true); setError(null); }
    try {
      const contacts = await fetchContacts(true);
      setLeads(contacts);
      if (!selectedLeadId && contacts.length > 0) {
        setSelectedLeadId(contacts[0].id);
      }
    } catch (e: any) {
      if (!silent) setError(e?.message || "Failed to load contacts");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [selectedLeadId]);

  const loadMessagesForLead = useCallback(async (id: string) => {
    try {
      const msgs = await fetchContactMessages(id);
      setAllMessages((prev) => {
        const others = prev.filter((m) => m.leadId !== id);
        return [...others, ...msgs];
      });
    } catch (e) {
      // Non-fatal: keep UI responsive.
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadContacts();
  }, [loadContacts]);

  // Poll for new contacts every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => loadContacts(true), 10_000);
    return () => clearInterval(interval);
  }, [loadContacts]);

  // Poll for new messages on selected lead every 5 seconds
  useEffect(() => {
    if (!selectedLeadId) return;
    const interval = setInterval(() => loadMessagesForLead(selectedLeadId), 5_000);
    return () => clearInterval(interval);
  }, [selectedLeadId, loadMessagesForLead]);

  useEffect(() => {
    if (selectedLeadId) {
      loadMessagesForLead(selectedLeadId);
    }
  }, [selectedLeadId, loadMessagesForLead]);

  const getFlowInfo = useCallback(() => {
    if (sortedLeads.length === 0) return null;
    const currentIndex = sortedLeads.findIndex((l) => l.id === selectedLeadId);
    const nextIndex = ((currentIndex >= 0 ? currentIndex : -1) + 1) % sortedLeads.length;
    const nextLead = sortedLeads[nextIndex];
    const waitingCount = leads.filter((l) => l.id !== selectedLeadId).length;
    if (!nextLead) return null;
    return {
      waitingCount,
      nextLeadName: nextLead.name,
      nextLeadTime: formatTimeInStage(nextLead.stageEnteredAt),
    };
  }, [sortedLeads, selectedLeadId, leads]);

  const handleSelectLead = useCallback(
    (id: string) => {
      setSelectedLeadId(id);
      if (isMobile) setMobileView("chat");
    },
    [isMobile],
  );

  const handleSendMessage = useCallback(
    async (text: string) => {
      if (!selectedLeadId) return;
      const optimistic: Message = {
        id: `tmp-${Date.now()}`,
        leadId: selectedLeadId,
        text,
        sender: "operator",
        timestamp: new Date().toISOString(),
      };
      setAllMessages((prev) => [...prev, optimistic]);
      try {
        await sendMessageToContact(selectedLeadId, text);
        await loadMessagesForLead(selectedLeadId);
        await loadContacts();
      } catch (e: any) {
        setError(e?.message || "Failed to send message");
      }
    },
    [selectedLeadId, loadMessagesForLead, loadContacts],
  );

  const handleUpdateLead = useCallback(
    async (updated: Lead) => {
      setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
      try {
        await setContactStage(updated.id, uiStageToBackend(updated.stage));
        await loadContacts();
      } catch (e: any) {
        setError(e?.message || "Failed to update stage");
      }
    },
    [loadContacts],
  );

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

  const handleNextLead = useCallback(() => {
    if (sortedLeads.length === 0) return;
    const currentIndex = sortedLeads.findIndex((l) => l.id === selectedLeadId);
    const nextIndex = ((currentIndex >= 0 ? currentIndex : -1) + 1) % sortedLeads.length;
    const nextLead = sortedLeads[nextIndex];
    if (nextLead) handleSelectLead(nextLead.id);
  }, [sortedLeads, selectedLeadId, handleSelectLead]);

  if (loading && leads.length === 0) {
    return <div className="h-screen flex items-center justify-center text-muted-foreground">Loading CRM...</div>;
  }

  if (error && leads.length === 0) {
    return <div className="h-screen flex items-center justify-center text-destructive">{error}</div>;
  }

  // Mobile layout
  if (isMobile) {
    return (
      <div className="h-[100dvh] flex flex-col bg-background">
        {error && <div className="px-3 py-2 text-xs text-destructive border-b border-destructive/30">{error}</div>}
        {mobileView === "list" && (
          <LeadList leads={leads} selectedLeadId={selectedLeadId} onSelectLead={handleSelectLead} />
        )}
        {mobileView === "chat" && selectedLead && (
          <div className="flex flex-col h-full">
            <div className="safe-top flex items-center justify-between px-1 py-1 border-b border-border bg-card/80 backdrop-blur-xl">
              <button
                onClick={() => setMobileView("list")}
                className="flex items-center gap-0.5 px-2 py-2 text-primary active:opacity-70 transition-opacity"
              >
                <ArrowLeft className="h-5 w-5" />
                <span className="text-sm font-medium">Leads</span>
              </button>
              <button
                onClick={() => setMobileView("details")}
                className="px-3 py-2 text-primary active:opacity-70 transition-opacity"
              >
                <PanelRightOpen className="h-5 w-5" />
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <ChatPanel
                lead={selectedLead}
                messages={leadMessages}
                onSendMessage={handleSendMessage}
                onNextLead={handleNextLead}
                onUpdateLead={handleUpdateLead}
                onEscalate={handleEscalate}
                flowInfo={getFlowInfo()}
              />
            </div>
          </div>
        )}
        {mobileView === "details" && selectedLead && (
          <div className="flex flex-col h-full">
            <div className="safe-top flex items-center px-1 py-1 border-b border-border bg-card/80 backdrop-blur-xl">
              <button
                onClick={() => setMobileView("chat")}
                className="flex items-center gap-0.5 px-2 py-2 text-primary active:opacity-70 transition-opacity"
              >
                <ArrowLeft className="h-5 w-5" />
                <span className="text-sm font-medium">Chat</span>
              </button>
              <span className="text-sm font-semibold text-foreground ml-auto mr-3">Details</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              <LeadDetails lead={selectedLead} onUpdateLead={handleUpdateLead} onSaveNotes={handleSaveNotes} onEscalate={handleEscalate} onToggleAffiliate={handleToggleAffiliate} onMarkAsNoise={handleMarkAsNoise} />
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      {error && <div className="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-2 text-xs text-destructive bg-card border border-destructive/30 rounded-xl z-50">{error}</div>}
      <div className="w-80 shrink-0 border-r border-border flex flex-col">
        <div className="flex items-center justify-end px-3 pt-2">
          <button onClick={handleLogout} className="p-1.5 text-muted-foreground hover:text-foreground transition-colors" title="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0">
          <LeadList leads={leads} selectedLeadId={selectedLeadId} onSelectLead={handleSelectLead} />
        </div>
      </div>
      <div className="flex-1 min-w-0">
        {selectedLead ? (
          <ChatPanel
            lead={selectedLead}
            messages={leadMessages}
            onSendMessage={handleSendMessage}
            onNextLead={handleNextLead}
            onUpdateLead={handleUpdateLead}
            onEscalate={handleEscalate}
            flowInfo={getFlowInfo()}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            Select a lead to start chatting
          </div>
        )}
      </div>
      {selectedLead && showDetails && (
        <div className="w-72 shrink-0">
          <LeadDetails lead={selectedLead} onUpdateLead={handleUpdateLead} onSaveNotes={handleSaveNotes} onEscalate={handleEscalate} onToggleAffiliate={handleToggleAffiliate} onMarkAsNoise={handleMarkAsNoise} />
        </div>
      )}
    </div>
  );
}
