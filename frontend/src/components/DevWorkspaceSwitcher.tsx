import { useEffect, useState } from "react";
import { saveAuth, getStoredUser } from "../api/auth";
import { fetchWorkspaces, impersonateWorkspace, Workspace } from "../api/workspaces";

const DEV_TOKEN_KEY = "crm_dev_token_backup";
const DEV_USER_KEY = "crm_dev_user_backup";

/**
 * Developer-only workspace impersonation control.
 *
 * Renders a small dropdown in the topbar listing every workspace in the system.
 * Selecting one calls /admin/impersonate, swaps the active JWT with one minted
 * for that workspace's org-owner Account, and reloads the page.
 *
 * Stashes the original developer token + user in `crm_dev_token_backup` /
 * `crm_dev_user_backup` so a "Return to developer view" button can restore it.
 */
export default function DevWorkspaceSwitcher() {
  const user = getStoredUser();
  const role = user?.role;
  const isDeveloper = role === "developer";
  const isImpersonating = !!localStorage.getItem(DEV_TOKEN_KEY);
  const showSwitcher = isDeveloper || isImpersonating;

  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!showSwitcher || !open || workspaces || loading) return;
    setLoading(true);
    fetchWorkspaces()
      .then(setWorkspaces)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [showSwitcher, open, workspaces, loading]);

  if (!showSwitcher) return null;

  async function pick(ws: Workspace) {
    if (!isImpersonating) {
      // First impersonation hop: stash the developer's own token + user.
      const t = localStorage.getItem("crm_token");
      const u = localStorage.getItem("crm_user");
      if (t) localStorage.setItem(DEV_TOKEN_KEY, t);
      if (u) localStorage.setItem(DEV_USER_KEY, u);
    }
    try {
      const r = await impersonateWorkspace(ws.id);
      saveAuth({
        username: r.username,
        role: r.role as never,
        token: r.access_token,
        workspace_id: r.workspace_id,
        workspace_name: r.workspace_name,
        org_id: r.org_id,
        org_role: r.org_role,
        account_id: r.account_id,
        onboarding_complete: r.onboarding_complete,
        parent_bot_username: r.parent_bot_username,
      });
      window.location.href = "/";
    } catch (e) {
      setError(String(e));
    }
  }

  function returnToDeveloper() {
    const t = localStorage.getItem(DEV_TOKEN_KEY);
    const u = localStorage.getItem(DEV_USER_KEY);
    if (!t || !u) {
      // Fallback: clear and bounce to login.
      localStorage.removeItem("crm_token");
      localStorage.removeItem("crm_user");
      window.location.href = "/login";
      return;
    }
    localStorage.setItem("crm_token", t);
    localStorage.setItem("crm_user", u);
    localStorage.removeItem(DEV_TOKEN_KEY);
    localStorage.removeItem(DEV_USER_KEY);
    window.location.href = "/";
  }

  return (
    <div className="relative">
      {isImpersonating && (
        <div className="mb-2 px-3 py-1.5 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-700 text-xs flex items-center gap-3">
          <span>
            Viewing as <span className="font-mono">{user?.username}</span> (workspace {user?.workspace_id})
          </span>
          <button
            onClick={returnToDeveloper}
            className="ml-auto text-amber-700 hover:text-amber-900 underline"
          >
            Return to developer view
          </button>
        </div>
      )}

      <button
        onClick={() => setOpen(o => !o)}
        className="text-xs px-3 py-1.5 rounded-md border border-border bg-secondary/50 hover:bg-secondary text-foreground"
      >
        Switch workspace ▾
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto bg-popover border border-border rounded-lg shadow-xl z-50">
          {loading && <div className="p-3 text-xs text-muted-foreground">Loading…</div>}
          {error && <div className="p-3 text-xs text-destructive">Error: {error}</div>}
          {workspaces && workspaces.length === 0 && (
            <div className="p-3 text-xs text-muted-foreground">No workspaces yet.</div>
          )}
          {workspaces && workspaces.map(ws => (
            <button
              key={ws.id}
              onClick={() => { setOpen(false); pick(ws); }}
              className="w-full text-left px-3 py-2 text-sm border-b border-border last:border-b-0 hover:bg-secondary/60"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">{ws.org_name || ws.name}</span>
                <span className="text-[10px] text-muted-foreground">#{ws.id}</span>
              </div>
              <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2">
                <span>{ws.owner_email ?? "(no owner account)"}</span>
                {ws.has_telethon && <span title="Telethon connected">●T</span>}
                {ws.has_bot_token && <span title="Bot token set">●B</span>}
                {ws.has_meta && <span title="Meta connected">●M</span>}
                {ws.onboarding_complete === false && (
                  <span className="text-amber-600" title="Onboarding incomplete">○</span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
