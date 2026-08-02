import { useCallback, useEffect, useState } from "react";

import { governedFetch } from "../api/context";
import { API_BASE_URL } from "../api/health";

interface Eligibility {
  eligible: boolean;
  generated_dataset_run_id: number | null;
  validation_run_id: number | null;
  date_min: string | null;
  date_max: string | null;
  eligible_record_counts: Record<string, number>;
  eligible_accounts: Array<{
    id: number;
    account_name: string;
    source_account_code: string;
    financial_account_code: string;
    transaction_count: number;
  }>;
  missing_prerequisites: string[];
  blocking_conditions: string[];
  warnings: string[];
  existing_run_id: number | null;
  generated_gl_strategy: string;
}

const LABELS: Record<string, string> = {
  bank_transactions: "Bank transactions",
  gl_cash_lines: "Cash GL lines",
  payroll_runs: "Payroll runs",
  payroll_entries: "Payroll entries",
  bank_withdrawals: "Bank withdrawals",
  gl_payroll_lines: "Payroll GL lines",
  customers: "Customers",
  crm_deals: "CRM deals",
  invoices: "Invoices",
  invoice_lines: "Invoice lines",
  customer_payments: "Payments",
  customer_payment_applications: "Payment applications",
  bank_deposits: "Bank deposits",
  gl_ar_lines: "AR GL lines",
};

export function ReconciliationReadiness({
  module,
}: {
  module: "bank-ledger" | "payroll" | "invoice-collections";
}) {
  const [value, setValue] = useState<Eligibility | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await governedFetch(
        `${API_BASE_URL}/reconciliations/${module}/eligibility`,
      );
      const body = (await response.json()) as Eligibility & { detail?: string };
      if (!response.ok) throw new Error(body.detail ?? `Eligibility failed (${response.status})`);
      setValue(body);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load eligibility");
    } finally {
      setLoading(false);
    }
  }, [module]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void load(), 0);
    window.addEventListener("reconciliation-inputs-changed", load);
    window.addEventListener("focus", load);
    return () => {
      window.clearTimeout(initialLoad);
      window.removeEventListener("reconciliation-inputs-changed", load);
      window.removeEventListener("focus", load);
    };
  }, [load]);

  if (loading && !value) return <p className="notice">Checking reconciliation readiness…</p>;
  if (error) return <p className="notice error">{error}</p>;
  if (!value) return null;

  const diagnostics = [...value.missing_prerequisites, ...value.blocking_conditions];
  return (
    <section className="readiness-panel" aria-label="Reconciliation readiness">
      <div className="section-heading">
        <div>
          <h3>{value.eligible ? "Ready to reconcile" : "Reconciliation prerequisites"}</h3>
          <p>
            Generated dataset {value.generated_dataset_run_id ? `#${value.generated_dataset_run_id}` : "not selected"}
            {" · "}validation {value.validation_run_id ? `#${value.validation_run_id}` : "required"}
            {" · "}{value.date_min ?? "—"} to {value.date_max ?? "—"}
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void load()}>
          Refresh readiness
        </button>
      </div>
      {diagnostics.map((item) => <p className="notice" key={item}>{item}</p>)}
      {value.warnings.map((item) => <p className="notice" key={item}>{item}</p>)}
      <div className="metric-grid">
        {Object.entries(value.eligible_record_counts).map(([key, count]) => (
          <div className="metric" key={key}><span>{LABELS[key] ?? key.replaceAll("_", " ")}</span><strong>{count}</strong></div>
        ))}
      </div>
      <p>
        Eligible accounts: {value.eligible_accounts.map((account) =>
          `${account.account_name} (${account.source_account_code} → GL ${account.financial_account_code})`
        ).join(", ") || "none"}.
      </p>
      <p className="muted">GL input: generated ledger adapter. {value.existing_run_id ? `Latest run #${value.existing_run_id}.` : "No prior run."}</p>
    </section>
  );
}
