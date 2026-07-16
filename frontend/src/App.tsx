import { useCallback, useEffect, useState } from "react";

import { API_BASE_URL, fetchHealth, type HealthResponse } from "./api/health";
import { CsvUploadPage } from "./components/CsvUploadPage";
import { GovernancePage } from "./components/GovernancePage";
import { GeneratedDataPage } from "./components/GeneratedDataPage";
import { MessyDataPage } from "./components/MessyDataPage";
import { ValidationPage } from "./components/ValidationPage";
import { ReconciliationPage } from "./components/ReconciliationPage";
import { PayrollReconciliationPage } from "./components/PayrollReconciliationPage";
import { IngestionCatalogPage } from "./components/IngestionCatalogPage";
import { CanonicalPage } from "./components/CanonicalPage";
import { StatusCard } from "./components/StatusCard";
import { DEFAULT_ACTOR, DEFAULT_TENANT, setDevelopmentContext } from "./api/context";
import { fetchTenants, type Tenant } from "./api/governance";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tenantCode, setTenantCode] = useState(localStorage.getItem("demoTenantCode") ?? DEFAULT_TENANT);
  const [actorEmail, setActorEmail] = useState(localStorage.getItem("demoActorEmail") ?? DEFAULT_ACTOR);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [page, setPage] = useState<"sources" | "staging" | "canonical" | "generated" | "messy" | "validation" | "reconciliation" | "payroll" | "governance">("sources");
  const [contextVersion, setContextVersion] = useState(0);

  const loadHealth = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      setHealth(await fetchHealth(signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError(requestError instanceof Error ? requestError.message : "Unable to load health data");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchHealth(controller.signal)
      .then((response) => setHealth(response))
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(
          requestError instanceof Error ? requestError.message : "Unable to load health data",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    setDevelopmentContext(tenantCode, actorEmail);
    void fetchTenants().then(setTenants).catch(() => setTenants([]));
  }, [tenantCode, actorEmail]);

  function changeContext(nextTenant: string, nextActor: string) {
    setDevelopmentContext(nextTenant, nextActor);
    setTenantCode(nextTenant);
    setActorEmail(nextActor);
    setContextVersion((value) => value + 1);
  }

  return (
    <main>
      <section className="panel status-panel">
        <div>
          <p className="eyebrow">CFO Financial Data Pipeline Demo</p>
          <h1>Source intake</h1>
          <p className="lede">Register raw financial source files without transforming them.</p>
        </div>
        <div className="health-summary">
          {loading && <p className="notice">Checking services...</p>}
          {error && <p className="notice error">{error}</p>}
          {health && (
            <div className="status-grid">
              <StatusCard label="Backend" status={health.backend.status} />
              <StatusCard label="Database" status={health.database.status} />
            </div>
          )}
          <p className="api-label">{health?.environment ?? "-"} · {API_BASE_URL}</p>
          <button type="button" onClick={() => void loadHealth()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh status"}
          </button>
        </div>
      </section>
      <section className="panel context-bar">
        <div><p className="eyebrow">Development context · Not authentication</p><strong>Tenant and actor simulation</strong></div>
        <label>Tenant<select value={tenantCode} onChange={(event) => changeContext(event.target.value, actorEmail)}>{tenants.length ? tenants.map((tenant) => <option key={tenant.id} value={tenant.code}>{tenant.display_name}</option>) : <option value={tenantCode}>{tenantCode}</option>}</select></label>
        <label>Demo user<select value={actorEmail} onChange={(event) => changeContext(tenantCode, event.target.value)}><option value="admin@demo.local">Platform admin</option><option value="cfo@demo.local">CFO user</option><option value="analyst@demo.local">Finance analyst</option><option value="viewer@demo.local">Client viewer</option></select></label>
        <nav><button type="button" className={page === "sources" ? "" : "secondary-button"} onClick={() => setPage("sources")}>Sources</button>{actorEmail !== "viewer@demo.local" && <button type="button" className={page === "staging" ? "" : "secondary-button"} onClick={() => setPage("staging")}>Staging & mappings</button>}<button type="button" className={page === "canonical" ? "" : "secondary-button"} onClick={() => setPage("canonical")}>Canonical</button><button type="button" className={page === "generated" ? "" : "secondary-button"} onClick={() => setPage("generated")}>Generated data</button><button type="button" className={page === "messy" ? "" : "secondary-button"} onClick={() => setPage("messy")}>Messy data</button><button type="button" className={page === "validation" ? "" : "secondary-button"} onClick={() => setPage("validation")}>Validation</button><button type="button" className={page === "reconciliation" ? "" : "secondary-button"} onClick={() => setPage("reconciliation")}>Bank reconciliation</button><button type="button" className={page === "payroll" ? "" : "secondary-button"} onClick={() => setPage("payroll")}>Payroll reconciliation</button><button type="button" className={page === "governance" ? "" : "secondary-button"} onClick={() => setPage("governance")}>Governance & audit</button></nav>
      </section>
      <div className="panel" key={`${tenantCode}-${actorEmail}-${contextVersion}`}>{page === "sources" ? <CsvUploadPage /> : page === "staging" ? <IngestionCatalogPage /> : page === "canonical" ? <CanonicalPage /> : page === "generated" ? <GeneratedDataPage /> : page === "messy" ? <MessyDataPage /> : page === "validation" ? <ValidationPage /> : page === "reconciliation" ? <ReconciliationPage /> : page === "payroll" ? <PayrollReconciliationPage /> : <GovernancePage />}</div>
    </main>
  );
}
