import { ReactNode, useState } from "react";
import AppSidebar from "./AppSidebar";
import { Menu } from "lucide-react";
import { useLocation } from "react-router-dom";

type PageMeta = { title: string; subtitle?: string };

const PAGE_META: Record<string, PageMeta> = {
  "/":           { title: "Dashboard",  subtitle: "An overview of your workspace" },
  "/leads":      { title: "Leads",      subtitle: "Conversations flowing through the pipeline" },
  "/analytics":  { title: "Analytics",  subtitle: "Funnel performance, signals, and trends" },
  "/members":    { title: "Members",    subtitle: "VIP channel membership" },
  "/affiliates": { title: "Affiliates", subtitle: "Partner performance and onboarding" },
  "/settings":   { title: "Settings",   subtitle: "Workspace and integrations" },
};

type AppLayoutProps = {
  children: ReactNode;
  /** When true, skip the built-in page header (for full-bleed pages like Leads). */
  bare?: boolean;
  /** Override the page title (defaults to pathname lookup). */
  title?: string;
  /** Override the subtitle. Pass empty string to hide. */
  subtitle?: string;
};

const AppLayout = ({ children, bare = false, title, subtitle }: AppLayoutProps) => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const meta = PAGE_META[location.pathname];
  const resolvedTitle = title ?? meta?.title ?? "Telelytics";
  const resolvedSubtitle = subtitle ?? meta?.subtitle;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Desktop sidebar */}
      <div className="hidden md:block">
        <AppSidebar />
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setSidebarOpen(false)}
          />
          <div className="relative z-50 w-64 h-full">
            <AppSidebar onNavigate={() => setSidebarOpen(false)} />
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="md:ml-64 flex flex-col min-h-screen">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 bg-sidebar/95 backdrop-blur border-b border-sidebar-border sticky top-0 z-40">
          <button
            onClick={() => setSidebarOpen(true)}
            className="-ml-1 p-1.5 text-muted-foreground hover:text-foreground transition-colors rounded-md"
            aria-label="Open navigation"
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="text-sm font-semibold text-foreground">{resolvedTitle}</span>
        </div>

        <div className={bare ? "flex-1 flex flex-col page-enter" : "flex-1 page-enter"}>
          {bare ? (
            children
          ) : (
            <div className="mx-auto w-full max-w-[1200px] px-5 md:px-8 py-6 md:py-8">
              <header className="mb-6 md:mb-8 hidden md:block">
                <h1 className="page-heading text-2xl">{resolvedTitle}</h1>
                {resolvedSubtitle && <p className="page-subheading">{resolvedSubtitle}</p>}
              </header>
              {children}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default AppLayout;
