import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import CRMDashboard from "./pages/CRMDashboard";
import AffiliateSelfDashboard from "./pages/AffiliateSelfDashboard";
import Login from "./pages/Login";
import { getToken, getStoredUser } from "./api/auth";

function PrivateRoute({ element }: { element: React.ReactElement }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  const user = getStoredUser();
  if (user?.role === "affiliate") return <Navigate to="/portal" replace />;
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
      <Route path="*" element={<PrivateRoute element={<CRMDashboard />} />} />
    </Routes>
  </BrowserRouter>
);

export default App;
