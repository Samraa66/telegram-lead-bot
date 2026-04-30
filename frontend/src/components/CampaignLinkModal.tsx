import { useEffect, useState } from "react";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

export interface CampaignLinkModalProps {
  campaign: {
    id: number;
    source_tag: string;
    name: string;
    link: string | null;            // bot deep link
    invite_link: string | null;     // channel invite — fetched if null
  };
  workspaceId: number;
  onClose: () => void;
}

export function CampaignLinkModal({ campaign, workspaceId, onClose }: CampaignLinkModalProps) {
  const [inviteLink, setInviteLink] = useState<string | null>(campaign.invite_link);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [selector, setSelector] = useState<string>("#join-button");

  useEffect(() => {
    if (campaign.invite_link) return;
    setInviteError(null);
    fetch(
      `${API_BASE}/attribution/invite?workspace_id=${workspaceId}&src=${encodeURIComponent(campaign.source_tag)}`,
    )
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          setInviteError(body.error || `HTTP ${r.status}`);
          return null;
        }
        return r.json();
      })
      .then(body => { if (body && body.invite_link) setInviteLink(body.invite_link); })
      .catch(e => setInviteError(String(e)));
  }, [campaign, workspaceId]);

  const snippet = `<script>
(async () => {
  const p = new URLSearchParams(window.location.search);
  const src = p.get('utm_campaign') || p.get('src') || 'organic';
  try {
    const r = await fetch(
      'https://telelytics.org/attribution/invite?workspace_id=${workspaceId}&src=' + encodeURIComponent(src),
      { mode: 'cors' }
    );
    if (r.ok) {
      const { invite_link } = await r.json();
      const el = document.querySelector(${JSON.stringify(selector)});
      if (el) el.href = invite_link;
    }
  } catch (e) { /* leave default href */ }
})();
</script>`;

  function copy(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 space-y-5">
        <div className="flex justify-between items-center">
          <h2 className="text-lg font-semibold">Tracked link created: {campaign.name}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-800">×</button>
        </div>

        <section>
          <h3 className="text-sm font-medium mb-1">1. Bot deep link (organic / direct)</h3>
          <div className="flex items-center gap-2">
            <code className="text-xs bg-gray-100 px-2 py-1 rounded flex-1 overflow-x-auto">
              {campaign.link || "(no BOT_USERNAME set)"}
            </code>
            {campaign.link && (
              <button onClick={() => copy(campaign.link!)} className="text-sm">Copy</button>
            )}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium mb-1">2. Channel invite link (paid traffic)</h3>
          <div className="flex items-center gap-2">
            <code className="text-xs bg-gray-100 px-2 py-1 rounded flex-1 overflow-x-auto">
              {inviteLink ?? (inviteError ? `Error: ${inviteError}` : "Minting...")}
            </code>
            {inviteLink && (
              <button onClick={() => copy(inviteLink)} className="text-sm">Copy</button>
            )}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-medium mb-1">3. Landing-page snippet</h3>
          <p className="text-xs text-gray-600 mb-2">
            Paste this onto your landing page once. It rewrites the Join button to the
            campaign-specific invite link based on the URL's <code>?utm_campaign</code>.
          </p>
          <div className="mb-2 flex items-center gap-2 text-xs">
            <label className="font-medium">Selector:</label>
            <input
              type="text"
              value={selector}
              onChange={e => setSelector(e.target.value)}
              className="border rounded px-2 py-1 w-48 font-mono"
            />
          </div>
          <div className="relative">
            <pre className="text-xs bg-gray-100 p-3 rounded overflow-x-auto whitespace-pre-wrap">
              {snippet}
            </pre>
            <button
              onClick={() => copy(snippet)}
              className="absolute top-2 right-2 text-xs"
            >Copy</button>
          </div>
        </section>
      </div>
    </div>
  );
}
