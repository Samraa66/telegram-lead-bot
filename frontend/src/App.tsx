import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import CRMDashboard from "./pages/CRMDashboard";
import Login from "./pages/Login";
import { getToken } from "./api/auth";

function PrivateRoute({ element }: { element: React.ReactElement }) {
  return getToken() ? element : <Navigate to="/login" replace />;
}

const App = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<PrivateRoute element={<CRMDashboard />} />} />
    </Routes>
  </BrowserRouter>
);

export default App;
