import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import { getToken, getStoredUser } from "./api/auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import LeadsPage from "./pages/LeadsPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import MembersPage from "./pages/MembersPage";
import AffiliatesPage from "./pages/AffiliatesPage";
import SettingsPage from "./pages/SettingsPage";
import OnboardingPage from "./pages/OnboardingPage";
import InvitePage from "./pages/InvitePage";

function PrivateRoute({ element, roles }: { element: React.ReactElement; roles?: string[] }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  const user = getStoredUser();
  // Affiliates who haven't finished onboarding go to the wizard first
  if (user?.role === "affiliate" && !user.onboarding_complete) {
    return <Navigate to="/onboarding" replace />;
  }
  if (roles && !roles.includes(user?.role || "")) return <Navigate to="/" replace />;
  return element;
}

function OnboardingRoute({ element }: { element: React.ReactElement }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  const user = getStoredUser();
  // Already done — send them to the app
  if (user?.onboarding_complete) return <Navigate to="/" replace />;
  return element;
}

const App = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/invite/:token" element={<InvitePage />} />
      <Route path="/onboarding" element={<OnboardingRoute element={<OnboardingPage />} />} />
      <Route path="/" element={<PrivateRoute element={<Dashboard />} />} />
      <Route path="/leads" element={<PrivateRoute element={<LeadsPage />} roles={["developer", "admin", "operator", "affiliate"]} />} />
      <Route path="/analytics" element={<PrivateRoute element={<AnalyticsPage />} roles={["developer", "admin", "operator", "affiliate"]} />} />
      <Route path="/members" element={<PrivateRoute element={<MembersPage />} roles={["developer", "admin", "vip_manager"]} />} />
      <Route path="/affiliates" element={<PrivateRoute element={<AffiliatesPage />} roles={["developer", "admin"]} />} />
      <Route path="/settings" element={<PrivateRoute element={<SettingsPage />} />} />
      {/* Legacy portal redirect — affiliates now use the full CRM */}
      <Route path="/portal" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </BrowserRouter>
);

export default App;
