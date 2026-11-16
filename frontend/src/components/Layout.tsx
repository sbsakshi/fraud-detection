import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useAnalyst } from "../lib/actor";

const Icon = ({ children }: { children: ReactNode }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{children}</svg>
);

export default function Layout() {
  const [analyst, setAnalyst] = useAnalyst();
  const { pathname } = useLocation();
  const summary = useQuery({ queryKey: ["case-summary"], queryFn: api.caseSummary, refetchInterval: 10_000 });
  const openCases = summary.data ? Object.values(summary.data.open_by_severity).reduce((a, b) => a + b, 0) : null;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round"><circle cx="5" cy="12" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 12l10-5.2M7 12l10 5.2" /></svg></span>
          Finsight
        </div>
        <nav className="nav" aria-label="Main">
          <div className="nav-label">Monitor</div>
          <NavLink to="/" end><Icon><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Icon>Analytics</NavLink>
          <div className="nav-label">Investigate</div>
          <NavLink to="/cases">
            <Icon><rect x="4" y="6" width="16" height="13" rx="3" /><path d="M9 6V4h6v2" /></Icon>
            Cases
            {openCases !== null && openCases > 0 && <span className="count">{openCases}</span>}
          </NavLink>
          <NavLink to="/transactions"><Icon><path d="M4 7h13l-3-3M20 17H7l3 3" /></Icon>Transactions</NavLink>
          <NavLink to="/network"><Icon><circle cx="6" cy="7" r="2.2" /><circle cx="18" cy="6" r="2.2" /><circle cx="12" cy="18" r="2.2" /><path d="M8 7.4l8 -1M7 9l4 7M17 8l-4 8" /></Icon>Network</NavLink>
          <div className="nav-label">Simulate</div>
          <NavLink to="/demo"><Icon><rect x="7" y="2.5" width="10" height="19" rx="2.5" /><path d="M11 18.5h2" /></Icon>Live demo</NavLink>
        </nav>
        <div className="sidebar-foot">
          <label htmlFor="analyst">Acting as</label>
          <input id="analyst" type="text" placeholder="Your name" defaultValue={analyst} onBlur={(e) => setAnalyst(e.target.value)} style={{ width: "100%" }} />
        </div>
      </aside>
      <main className={`main ${(pathname.startsWith("/network") || pathname.startsWith("/demo")) ? "bleed" : ""}`}>
        <Outlet />
      </main>
    </div>
  );
}
