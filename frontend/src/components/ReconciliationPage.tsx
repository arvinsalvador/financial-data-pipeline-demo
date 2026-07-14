import { useEffect, useState } from "react";

import {
  decideMatchGroup,
  fetchMatchGroups,
  fetchReconciliationAccounts,
  fetchReconciliationControls,
  fetchReconciliationExceptions,
  fetchReconciliationReports,
  fetchReconciliationRuns,
  runReconciliation,
  type BankAccount,
  type Control,
  type MatchGroup,
  type ReconciliationException,
  type ReconciliationRun,
  type Report,
} from "../api/reconciliation";

export function ReconciliationPage() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [runs, setRuns] = useState<ReconciliationRun[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [groups, setGroups] = useState<MatchGroup[]>([]);
  const [exceptions, setExceptions] = useState<ReconciliationException[]>([]);
  const [controls, setControls] = useState<Control[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [dateFrom, setDateFrom] = useState("2025-01-01");
  const [dateTo, setDateTo] = useState("2026-12-31");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = runs.find((run) => run.id === selectedId) ?? null;

  async function loadRuns() {
    const next = await fetchReconciliationRuns();
    setRuns(next);
    setSelectedId((current) => current ?? next[0]?.id ?? null);
  }
  useEffect(() => {
    void Promise.all([fetchReconciliationAccounts(), fetchReconciliationRuns()])
      .then(([nextAccounts, nextRuns]) => {
        setAccounts(nextAccounts);
        setRuns(nextRuns);
        setSelectedId(nextRuns[0]?.id ?? null);
      })
      .catch((value: unknown) => setError(value instanceof Error ? value.message : "Unable to load reconciliation"));
  }, []);
  useEffect(() => {
    if (!selectedId) return;
    void Promise.all([
      fetchMatchGroups(selectedId).then(setGroups),
      fetchReconciliationExceptions(selectedId).then(setExceptions),
      fetchReconciliationControls(selectedId).then(setControls),
      fetchReconciliationReports(selectedId).then(setReports),
    ]).catch((value: unknown) => setError(value instanceof Error ? value.message : "Unable to load reconciliation detail"));
  }, [selectedId]);

  async function execute() {
    if (!accounts[0]) return;
    setBusy(true); setError(null);
    try {
      const result = await runReconciliation(accounts[0].id, dateFrom, dateTo);
      await loadRuns(); setSelectedId(result.id);
    } catch (value) { setError(value instanceof Error ? value.message : "Reconciliation failed"); }
    finally { setBusy(false); }
  }
  async function decide(group: MatchGroup, decision: "accept" | "reject" | "resolve" | "reopen") {
    if (!selectedId) return;
    setBusy(true); setError(null);
    try {
      await decideMatchGroup(selectedId, group.id, decision, `Operator ${decision} from reconciliation workbench`);
      setGroups(await fetchMatchGroups(selectedId)); await loadRuns();
    } catch (value) { setError(value instanceof Error ? value.message : "Decision failed"); }
    finally { setBusy(false); }
  }

  return <section>
    <p className="eyebrow">Phase 9 · Version 1.0.0</p><h2>Bank-to-ledger reconciliation</h2>
    <p>Match canonical bank activity to generated cash-ledger lines with deterministic evidence and controlled review.</p>
    {error && <p className="notice error">{error}</p>}
    <div className="form-grid">
      <label>Bank account<select>{accounts.map((account) => <option key={account.id} value={account.id}>{account.account_name} · {account.source_account_code}</option>)}</select></label>
      <label>Date from<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label>Date to<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      <button type="button" disabled={busy || !accounts.length} onClick={() => void execute()}>{busy ? "Working…" : "Run reconciliation"}</button>
    </div>
    <label>Run<select value={selectedId ?? ""} onChange={(event) => setSelectedId(Number(event.target.value))}><option value="">Select a run</option>{runs.map((run) => <option key={run.id} value={run.id}>#{run.id} · {run.date_from} to {run.date_to} · {run.status}</option>)}</select></label>
    {selected && <>
      <div className="status-grid">
        <article><strong>{(Number(selected.reconciliation_rate) * 100).toFixed(1)}%</strong><p>Reconciled</p></article>
        <article><strong>{selected.automatically_matched_count}</strong><p>Automatic groups</p></article>
        <article><strong>{selected.suggested_match_count}</strong><p>Needs review</p></article>
        <article><strong>{selected.exception_count}</strong><p>Exceptions</p></article>
      </div>
      <h3>Match review</h3><div className="table-wrap"><table><thead><tr><th>Group</th><th>Type</th><th>Status</th><th>Amount</th><th>Confidence</th><th>Action</th></tr></thead><tbody>{groups.map((group) => <tr key={group.id}><td>#{group.id}</td><td>{group.group_type}</td><td>{group.status}</td><td>{group.matched_amount}</td><td>{(Number(group.confidence) * 100).toFixed(1)}%</td><td>{["suggested", "needs_review", "partially_matched", "reopened"].includes(group.status) && <><button type="button" disabled={busy} onClick={() => void decide(group, "accept")}>Accept</button> <button className="secondary-button" type="button" disabled={busy} onClick={() => void decide(group, "reject")}>Reject</button></>}{["matched", "resolved", "rejected"].includes(group.status) && <button className="secondary-button" type="button" disabled={busy} onClick={() => void decide(group, "reopen")}>Reopen</button>}</td></tr>)}</tbody></table></div>
      <h3>Control totals</h3><div className="table-wrap"><table><thead><tr><th>Control</th><th>Source</th><th>Matched</th><th>Difference</th><th>Status</th></tr></thead><tbody>{controls.map((control) => <tr key={control.id}><td>{control.control_name}</td><td>{control.source_value}</td><td>{control.matched_value}</td><td>{control.difference_value}</td><td>{control.status}</td></tr>)}</tbody></table></div>
      <h3>Open exceptions</h3><p>{exceptions.filter((item) => item.status === "open").length} open · duplicates {selected.duplicate_count} · reversals {selected.reversal_count}</p>
      <h3>Reports</h3><ul>{reports.map((report) => <li key={report.id}><strong>{report.report_type}</strong> · {report.relative_path} · {report.file_size_bytes} bytes</li>)}</ul>
    </>}
  </section>;
}
