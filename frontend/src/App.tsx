import { useCallback, useEffect, useState } from "react";

import { API_BASE_URL, fetchHealth, type HealthResponse } from "./api/health";
import { CsvUploadPage } from "./components/CsvUploadPage";
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
      <div className="panel"><CsvUploadPage /></div>
    </main>
  );
}
