import { Link, useLocation } from "react-router-dom";
import { LayoutDashboard, Users, BarChart3, Star, UserPlus, Settings, Send, LogOut, ChevronUp } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { clearAuth, getStoredUser } from "@/api/auth";

const ALL_NAV_ITEMS = [
  { label: "Dashboard",  icon: LayoutDashboard, path: "/",           roles: null },
  { label: "Leads",      icon: Users,           path: "/leads",      roles: ["developer", "admin", "operator"] },
  { label: "Analytics",  icon: BarChart3,        path: "/analytics",  roles: ["developer", "admin", "operator"] },
  { label: "Members",    icon: Star,             path: "/members",    roles: ["developer", "admin", "vip_manager"] },
  { label: "Affiliates", icon: UserPlus,         path: "/affiliates", roles: ["developer", "admin"] },
  { label: "Settings",   icon: Settings,         path: "/settings",   roles: null },
];

const AppSidebar = ({ onNavigate }: { onNavigate?: () => void } = {}) => {
  const location = useLocation();
  const storedUser = getStoredUser();
  const role = storedUser?.role || "";
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
