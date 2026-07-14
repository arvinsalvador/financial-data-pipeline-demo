import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";

interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface BankAccount { id: number; account_name: string; source_account_code: string; institution_name: string | null; status: string }
export interface ReconciliationRun { id: number; reconciliation_version: string; status: string; date_from: string; date_to: string; bank_account_id: number; included_bank_transaction_count: number; included_ledger_line_count: number; automatically_matched_count: number; suggested_match_count: number; unmatched_bank_count: number; unmatched_ledger_count: number; duplicate_count: number; reversal_count: number; exception_count: number; total_bank_amount: string; total_ledger_amount: string; total_matched_amount: string; reconciliation_rate: string; no_op: boolean }
export interface MatchGroup { id: number; group_type: string; status: string; confidence: string; matched_amount: string; bank_total: string; ledger_total: string; difference_amount: string; auto_accepted: boolean; notes: string | null; metadata_json: { bank_records?: Record<string, string | number>[]; ledger_records?: Record<string, string | number>[] } | null }
export interface ReconciliationException { id: number; exception_code: string; exception_type: string; severity: string; bank_transaction_id: number | null; ledger_record_id: string | null; status: string; message: string }
export interface Control { id: number; control_name: string; source_value: string; matched_value: string; unmatched_value: string; difference_value: string; status: string }
export interface Report { id: number; report_type: string; relative_path: string; checksum: string; file_size_bytes: number }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await governedFetch(`${API_BASE_URL}${path}`, init);
  const body = (await response.json()) as T & { detail?: string };
  if (!response.ok) throw new Error(body.detail ?? `Request failed (${response.status})`);
  return body;
}
export function fetchReconciliationAccounts() { return request<BankAccount[]>("/reconciliations/bank-ledger/accounts"); }
export async function fetchReconciliationRuns() { return (await request<Page<ReconciliationRun>>("/reconciliations/bank-ledger/runs?page_size=100")).items; }
export function runReconciliation(bankAccountId: number, dateFrom: string, dateTo: string, force = false) { return request<ReconciliationRun>("/reconciliations/bank-ledger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_account_id: bankAccountId, date_from: dateFrom, date_to: dateTo, force_rerun: force }) }); }
export async function fetchMatchGroups(runId: number) { return (await request<Page<MatchGroup>>(`/reconciliations/bank-ledger/runs/${runId}/groups?page_size=500`)).items; }
export async function fetchReconciliationExceptions(runId: number) { return (await request<Page<ReconciliationException>>(`/reconciliations/bank-ledger/runs/${runId}/exceptions?page_size=500`)).items; }
export function fetchReconciliationControls(runId: number) { return request<Control[]>(`/reconciliations/bank-ledger/runs/${runId}/controls`); }
export function fetchReconciliationReports(runId: number) { return request<Report[]>(`/reconciliations/bank-ledger/runs/${runId}/reports`); }
export function decideMatchGroup(runId: number, groupId: number, decision: "accept" | "reject" | "resolve" | "reopen", reason: string) { return request(`/reconciliations/bank-ledger/runs/${runId}/groups/${groupId}/decisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, reason }) }); }
