import { Link, useLocation } from "react-router-dom";
import { LayoutDashboard, Users, BarChart3, Star, UserPlus, Settings, Send, LogOut, ChevronUp, ChevronDown, Building2, Plus, Check } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { clearAuth, getStoredUser, switchWorkspace } from "@/api/auth";
import { fetchOrgWorkspaces, createOrgWorkspace, type Workspace } from "@/api/workspaces";
import { cn } from "@/lib/utils";

const ALL_NAV_ITEMS = [
  { label: "Dashboard",  icon: LayoutDashboard, path: "/",           roles: null },
  { label: "Leads",      icon: Users,           path: "/leads",      roles: ["developer", "admin", "operator"] },
  { label: "Analytics",  icon: BarChart3,        path: "/analytics",  roles: ["developer", "admin", "operator"] },
  { label: "Members",    icon: Star,             path: "/members",    roles: ["developer", "admin", "vip_manager"] },
  { label: "Affiliates", icon: UserPlus,         path: "/affiliates", roles: ["developer", "admin"] },
  { label: "Settings",   icon: Settings,         path: "/settings",   roles: null },
];

// ---------------------------------------------------------------------------
// Workspace switcher — developer only
// ---------------------------------------------------------------------------

function WorkspaceSwitcher({ currentWorkspaceId }: { currentWorkspaceId: number }) {
  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState(false);
  // creating: null = not creating, number = parent_workspace_id to create under
  const [creatingUnder, setCreatingUnder] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const current = workspaces.find(w => w.id === currentWorkspaceId);

  useEffect(() => {
    fetchOrgWorkspaces()
      .then(setWorkspaces)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setCreatingUnder(null);
        setNewName("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  async function handleSwitch(workspaceId: number) {
    if (workspaceId === currentWorkspaceId || switching) return;
    setSwitching(true);
    try {
      await switchWorkspace(workspaceId);
      window.location.reload();
    } catch {
      setSwitching(false);
    }
  }

  async function handleCreate() {
    if (!newName.trim() || loading || creatingUnder === null) return;
    setLoading(true);
    try {
      const created = await createOrgWorkspace(newName.trim(), creatingUnder);
      setWorkspaces(prev => [...prev, created]);
      setNewName("");
      setCreatingUnder(null);
      await handleSwitch(created.id);
    } catch {
      setLoading(false);
    }
  }

  // Build a simple tree: map from parent_id → children
  const roots = workspaces.filter(w => w.parent_workspace_id === null);
  const childrenOf = (parentId: number) => workspaces.filter(w => w.parent_workspace_id === parentId);

  function renderWorkspace(ws: Workspace, depth: number): React.ReactNode {
    const children = childrenOf(ws.id);
    const isCurrent = ws.id === currentWorkspaceId;
    const indent = depth * 12;
    return (
      <div key={ws.id}>
        <button
          onClick={() => handleSwitch(ws.id)}
          disabled={switching}
          className={cn(
            "w-full flex items-center gap-2 py-2 pr-3 text-sm transition-colors text-left",
            isCurrent
              ? "text-[hsl(199,86%,45%)] bg-[hsl(199,86%,55%)]/5"
              : "text-foreground hover:bg-muted"
          )}
          style={{ paddingLeft: `${16 + indent}px` }}
        >
          {isCurrent
            ? <Check className="w-3.5 h-3.5 shrink-0" />
            : <Building2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
          }
          <span className="flex-1 truncate">{ws.name}</span>
          <span className="flex gap-1 items-center">
            {ws.workspace_role === "affiliate" && (
              <span className="text-[10px] text-muted-foreground bg-muted rounded px-1 leading-4">aff</span>
            )}
            {ws.has_telethon && <span className="w-1.5 h-1.5 rounded-full bg-green-500" title="Telethon connected" />}
            {ws.has_meta    && <span className="w-1.5 h-1.5 rounded-full bg-blue-500" title="Meta connected" />}
            <button
              onClick={e => { e.stopPropagation(); setCreatingUnder(ws.id); setNewName(""); }}
              className="ml-1 p-0.5 rounded hover:bg-border transition-colors"
              title={`Add affiliate under ${ws.name}`}
            >
              <Plus className="w-3 h-3 text-muted-foreground" />
            </button>
          </span>
        </button>
        {children.map(child => renderWorkspace(child, depth + 1))}
      </div>
    );
  }

  return (
    <div className="px-3 pb-1 relative" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm hover:bg-sidebar-accent transition-colors"
      >
        <Building2 className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        <span className="flex-1 text-left text-xs text-muted-foreground truncate">
          {current?.name ?? `Workspace ${currentWorkspaceId}`}
        </span>
        <ChevronDown className={cn("w-3 h-3 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute bottom-full left-3 right-3 mb-1 bg-card border border-border rounded-xl shadow-xl overflow-hidden z-50 max-h-80 overflow-y-auto">
          <div className="py-1">
            {roots.map(ws => renderWorkspace(ws, 0))}
          </div>

          {creatingUnder !== null && (
            <div className="border-t border-border px-3 py-2">
              <p className="text-[10px] text-muted-foreground mb-1.5">
                New affiliate under <strong>{workspaces.find(w => w.id === creatingUnder)?.name}</strong>
              </p>
              <div className="flex items-center gap-1.5">
                <input
                  autoFocus
                  className="flex-1 text-xs border rounded-md px-2 py-1.5 bg-background"
                  placeholder="Workspace name…"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter") handleCreate();
                    if (e.key === "Escape") { setCreatingUnder(null); setNewName(""); }
                  }}
                />
                <button
                  onClick={handleCreate}
                  disabled={loading || !newName.trim()}
                  className="px-2 py-1.5 text-xs rounded-md bg-[hsl(199,86%,55%)] text-white disabled:opacity-50"
                >
                  {loading ? "…" : "Add"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

const AppSidebar = ({ onNavigate }: { onNavigate?: () => void } = {}) => {
  const location = useLocation();
  const storedUser = getStoredUser();
  const role = storedUser?.role || "";
  const orgRole = storedUser?.org_role ?? "member";
  const workspaceId = storedUser?.workspace_id ?? 1;
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const navItems = ALL_NAV_ITEMS.filter(
    (item) => !item.roles || item.roles.includes(role)
  );

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleLogout = () => {
    clearAuth();
    window.location.href = "/login";
  };

  const initials = (storedUser?.username || "U").slice(0, 2).toUpperCase();

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-sidebar border-r border-sidebar-border flex flex-col z-50">
      {/* Logo */}
      <div className="p-6 flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl gradient-primary flex items-center justify-center shrink-0">
          <Send className="w-5 h-5 text-primary-foreground" />
        </div>
        <div>
          <h1 className="text-base font-bold text-foreground tracking-tight">Telelytics</h1>
          <p className="text-xs text-muted-foreground">CRM Platform</p>
        </div>
      </div>

      {/* Workspace switcher — org owners only */}
      {orgRole === "org_owner" && (
        <WorkspaceSwitcher currentWorkspaceId={workspaceId} />
      )}

      {/* Nav */}
      <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = item.path === "/"
            ? location.pathname === "/"
            : location.pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={onNavigate}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                isActive
                  ? "bg-primary/10 text-primary glow-primary"
                  : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              }`}
            >
              <item.icon className="w-4 h-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* User section */}
      <div className="p-3 relative" ref={menuRef}>
        {userMenuOpen && (
          <div className="absolute bottom-full left-3 right-3 mb-1 bg-card border border-border rounded-xl shadow-xl overflow-hidden z-50">
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-2.5 px-4 py-3 text-sm text-destructive hover:bg-destructive/10 transition-colors"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </button>
          </div>
        )}
        <button
          onClick={() => setUserMenuOpen((v) => !v)}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-sidebar-accent transition-all"
        >
          <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
            <span className="text-primary text-xs font-bold">{initials}</span>
          </div>
          <div className="flex-1 text-left min-w-0">
            <p className="text-xs font-semibold text-foreground truncate">{storedUser?.username || "User"}</p>
            <p className="text-[11px] text-muted-foreground capitalize">{role}</p>
          </div>
          <ChevronUp className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${userMenuOpen ? "" : "rotate-180"}`} />
        </button>
      </div>
    </aside>
  );
};

export default AppSidebar;
