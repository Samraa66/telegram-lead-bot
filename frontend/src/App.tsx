import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import { getToken, getStoredUser } from "./api/auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import LeadsPage from "./pages/LeadsPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import MembersPage from "./pages/MembersPage";
import AffiliatesPage from "./pages/AffiliatesPage";
import SettingsPage from "./pages/SettingsPage";
import AffiliateSelfDashboard from "./pages/AffiliateSelfDashboard";

function PrivateRoute({ element, roles }: { element: React.ReactElement; roles?: string[] }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  const user = getStoredUser();
  if (user?.role === "affiliate") return <Navigate to="/portal" replace />;
  if (roles && !roles.includes(user?.role || "")) return <Navigate to="/" replace />;
  return element;
}

function AffiliateRoute({ element }: { element: React.ReactElement }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  const user = getStoredUser();
  if (user?.role !== "affiliate") return <Navigate to="/" replace />;
  return element;
}

const App = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/portal" element={<AffiliateRoute element={<AffiliateSelfDashboard />} />} />
      <Route path="/" element={<PrivateRoute element={<Dashboard />} />} />
      <Route path="/leads" element={<PrivateRoute element={<LeadsPage />} roles={["developer", "admin", "operator"]} />} />
      <Route path="/analytics" element={<PrivateRoute element={<AnalyticsPage />} roles={["developer", "admin", "operator"]} />} />
      <Route path="/members" element={<PrivateRoute element={<MembersPage />} roles={["developer", "admin", "vip_manager"]} />} />
      <Route path="/affiliates" element={<PrivateRoute element={<AffiliatesPage />} roles={["developer", "admin"]} />} />
      <Route path="/settings" element={<PrivateRoute element={<SettingsPage />} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </BrowserRouter>
);

export default App;
