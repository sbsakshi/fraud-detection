import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Account from "./pages/Account";
import CaseDetail from "./pages/CaseDetail";
import Demo from "./pages/Demo";
import Cases from "./pages/Cases";
import Network from "./pages/Network";
import Analytics from "./pages/Analytics";
import Transactions from "./pages/Transactions";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Analytics />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/:caseId" element={<CaseDetail />} />
        <Route path="accounts/:upiId" element={<Account />} />
        <Route path="demo" element={<Demo />} />
        <Route path="network" element={<Network />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
