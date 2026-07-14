import { useCallback, useEffect, useState } from "react";

import { API_BASE_URL, fetchHealth, type HealthResponse } from "./api/health";
import { StatusCard } from "./components/StatusCard";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <main>
      <section className="panel">
        <p className="eyebrow">Phase 1 · Platform foundation</p>
        <h1>{health?.application ?? "CFO Financial Data Pipeline Demo"}</h1>
        <p className="lede">Container and database connectivity status</p>

        {loading && <p className="notice">Checking services…</p>}
        {error && <p className="notice error">{error}</p>}

        {health && (
          <div className="status-grid">
            <StatusCard label="Backend" status={health.backend.status} />
            <StatusCard label="Database" status={health.database.status} />
          </div>
        )}

        <dl>
          <div>
            <dt>Environment</dt>
            <dd>{health?.environment ?? "—"}</dd>
          </div>
          <div>
            <dt>API base URL</dt>
            <dd>{API_BASE_URL}</dd>
          </div>
        </dl>

        <button type="button" onClick={() => void loadHealth()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh status"}
        </button>
      </section>
    </main>
  );
}
