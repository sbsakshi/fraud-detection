import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Account from "./pages/Account";
import CaseDetail from "./pages/CaseDetail";
import Cases from "./pages/Cases";
import Network from "./pages/Network";
import Overview from "./pages/Overview";
import Transactions from "./pages/Transactions";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/:caseId" element={<CaseDetail />} />
        <Route path="accounts/:upiId" element={<Account />} />
        <Route path="network" element={<Network />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
