import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { HealthResponse } from "../api/health";
import type { Tenant } from "../api/governance";
import { NAVIGATION, PAGE_COPY, type PageKey } from "../navigation";

const ACTORS = [
  ["admin@demo.local", "Platform administrator"],
  ["cfo@demo.local", "CFO user"],
  ["analyst@demo.local", "Finance analyst"],
  ["viewer@demo.local", "Client viewer"],
] as const;

function Navigation({ page, actor, collapsed, onNavigate }: { page: PageKey; actor: string; collapsed: boolean; onNavigate: (page: PageKey) => void }) {
  const visible = NAVIGATION.filter((item) => actor !== "viewer@demo.local" || item.viewerVisible);
  const groups = [...new Set(visible.map((item) => item.group))];
  return <nav className="primary-navigation" aria-label="Primary navigation">{groups.map((group) => <section className="navigation-group" key={group}><h2 className={visible.some((item) => item.group === group && item.page === page) ? "group-active" : ""}>{collapsed ? <span className="sr-only">{group}</span> : group}</h2>{visible.filter((item) => item.group === group).map((item) => <button key={item.page} type="button" className="navigation-link" aria-current={item.page === page ? "page" : undefined} title={collapsed ? item.label : undefined} onClick={() => onNavigate(item.page)}><span className="navigation-icon" aria-hidden="true">{item.icon}</span>{!collapsed && <span>{item.label}</span>}</button>)}</section>)}</nav>;
}

function HealthPill({ label, status }: { label: string; status: string }) {
  const normalized = status === "healthy" ? "healthy" : status === "degraded" ? "degraded" : "unavailable";
  return <span className={`health-pill health-${normalized}`} role="status" aria-label={`${label}: ${normalized}`}><i aria-hidden="true" />{label}: {normalized}</span>;
}

export function AppShell({ page, actorEmail, tenantCode, tenants, health, healthLoading, healthError, onRefreshHealth, onContextChange, onNavigate, children }: { page: PageKey; actorEmail: string; tenantCode: string; tenants: Tenant[]; health: HealthResponse | null; healthLoading: boolean; healthError: string | null; onRefreshHealth: () => void; onContextChange: (tenant: string, actor: string) => void; onNavigate: (page: PageKey) => void; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(localStorage.getItem("demoSidebarCollapsed") === "true");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const role = useMemo(() => ACTORS.find(([email]) => email === actorEmail)?.[1] ?? "Development actor", [actorEmail]);
  useEffect(() => { localStorage.setItem("demoSidebarCollapsed", String(collapsed)); }, [collapsed]);
  useEffect(() => {
    if (!drawerOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setDrawerOpen(false); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [drawerOpen]);
  const navigate = (next: PageKey) => { onNavigate(next); setDrawerOpen(false); };
  return <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""} ${actorEmail === "viewer@demo.local" ? "viewer-context" : ""}`}>
    <aside className="desktop-sidebar" aria-label="Application sidebar">
      <div className="brand"><span className="brand-mark">CFO</span>{!collapsed && <div><strong>Financial Pipeline</strong><small>Demonstration workspace</small></div>}</div>
      <Navigation page={page} actor={actorEmail} collapsed={collapsed} onNavigate={navigate} />
      <button type="button" className="sidebar-toggle" aria-expanded={!collapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setCollapsed((value) => !value)}>{collapsed ? "›" : "‹ Collapse"}</button>
    </aside>
    {drawerOpen && <button className="drawer-backdrop" type="button" aria-label="Close navigation" onClick={() => setDrawerOpen(false)} />}
    <aside className={`mobile-drawer ${drawerOpen ? "open" : ""}`} aria-label="Mobile navigation" aria-hidden={!drawerOpen}><div className="drawer-heading"><strong>Navigation</strong><button className="icon-button" type="button" aria-label="Close navigation" onClick={() => setDrawerOpen(false)}>×</button></div><Navigation page={page} actor={actorEmail} collapsed={false} onNavigate={navigate} /></aside>
    <div className="app-workspace">
      <header className="app-header">
        <button className="mobile-menu icon-button" type="button" aria-label="Open navigation" aria-controls="mobile-navigation" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}>☰</button>
        <div className="environment-context"><span className="environment-badge">Development</span><span>Header context is not authentication</span></div>
        <div className="health-cluster">{healthLoading ? <span className="health-pill">Checking services…</span> : health ? <><HealthPill label="Backend" status={health.backend.status} /><HealthPill label="Database" status={health.database.status} /></> : <span className="health-pill health-unavailable">Services unavailable</span>}<button className="icon-button" type="button" aria-label="Refresh service health" title="Refresh service health" disabled={healthLoading} onClick={onRefreshHealth}>↻</button></div>
        <div className="context-controls"><label><span>Tenant</span><select value={tenantCode} onChange={(event) => onContextChange(event.target.value, actorEmail)}>{tenants.length ? tenants.map((tenant) => <option key={tenant.id} value={tenant.code}>{tenant.display_name}</option>) : <option value={tenantCode}>{tenantCode}</option>}</select></label><label><span>Demo user</span><select value={actorEmail} onChange={(event) => onContextChange(tenantCode, event.target.value)}>{ACTORS.map(([email, label]) => <option key={email} value={email}>{label}</option>)}</select></label><div className="role-display"><span>Current role</span><strong>{role}</strong></div></div>
        {healthError && <p className="header-error" role="alert">{healthError}</p>}
      </header>
      <main className="main-content" id="main-content"><div className="page-container"><header className="page-header"><p className="eyebrow">CFO Financial Data Pipeline Demo</p><h1>{PAGE_COPY[page].title}</h1><p>{PAGE_COPY[page].description}</p></header><div className="content-panel">{children}</div></div></main>
    </div>
  </div>;
}
