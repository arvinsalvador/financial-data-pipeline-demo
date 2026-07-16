import { useCallback, useEffect, useState } from "react";

import { DEFAULT_ACTOR, DEFAULT_TENANT, setDevelopmentContext } from "./api/context";
import { fetchTenants, type Tenant } from "./api/governance";
import { fetchHealth, type HealthResponse } from "./api/health";
import { AppShell } from "./components/AppShell";
import { CanonicalPage } from "./components/CanonicalPage";
import { CsvUploadPage } from "./components/CsvUploadPage";
import { GeneratedDataPage } from "./components/GeneratedDataPage";
import { GovernancePage } from "./components/GovernancePage";
import { IngestionCatalogPage } from "./components/IngestionCatalogPage";
import { InvoiceCollectionsPage } from "./components/InvoiceCollectionsPage";
import { MessyDataPage } from "./components/MessyDataPage";
import { PayrollReconciliationPage } from "./components/PayrollReconciliationPage";
import { ReconciliationPage } from "./components/ReconciliationPage";
import { ValidationPage } from "./components/ValidationPage";
import type { PageKey } from "./navigation";

const PAGES: Record<PageKey, () => React.JSX.Element> = { sources: CsvUploadPage, staging: IngestionCatalogPage, canonical: CanonicalPage, generated: GeneratedDataPage, messy: MessyDataPage, validation: ValidationPage, reconciliation: ReconciliationPage, payroll: PayrollReconciliationPage, collections: InvoiceCollectionsPage, governance: GovernancePage };

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tenantCode, setTenantCode] = useState(localStorage.getItem("demoTenantCode") ?? DEFAULT_TENANT);
  const [actorEmail, setActorEmail] = useState(localStorage.getItem("demoActorEmail") ?? DEFAULT_ACTOR);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [page, setPage] = useState<PageKey>("sources");
  const [contextVersion, setContextVersion] = useState(0);
  const loadHealth = useCallback(async (signal?: AbortSignal) => { setLoading(true); setError(null); try { setHealth(await fetchHealth(signal)); } catch (requestError) { if (!(requestError instanceof DOMException && requestError.name === "AbortError")) setError(requestError instanceof Error ? requestError.message : "Unable to load health data"); } finally { if (!signal?.aborted) setLoading(false); } }, []);
  useEffect(() => { const controller = new AbortController(); void fetchHealth(controller.signal).then(setHealth).catch((requestError: unknown) => { if (!(requestError instanceof DOMException && requestError.name === "AbortError")) setError(requestError instanceof Error ? requestError.message : "Unable to load health data"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, []);
  useEffect(() => { setDevelopmentContext(tenantCode, actorEmail); void fetchTenants().then(setTenants).catch(() => setTenants([])); }, [tenantCode, actorEmail]);
  function changeContext(nextTenant: string, nextActor: string) { setDevelopmentContext(nextTenant, nextActor); setTenantCode(nextTenant); setActorEmail(nextActor); setContextVersion((value) => value + 1); }
  const Page = PAGES[page];
  return <AppShell page={page} actorEmail={actorEmail} tenantCode={tenantCode} tenants={tenants} health={health} healthLoading={loading} healthError={error} onRefreshHealth={() => void loadHealth()} onContextChange={changeContext} onNavigate={setPage}><div key={`${tenantCode}-${actorEmail}-${contextVersion}`}><Page /></div></AppShell>;
}
