import { BrowserRouter, Route, Routes } from "react-router-dom";
import CRMDashboard from "./pages/CRMDashboard";

const App = () => (
  <BrowserRouter>
    <Routes>
      <Route path="*" element={<CRMDashboard />} />
    </Routes>
  </BrowserRouter>
);

export default App;
