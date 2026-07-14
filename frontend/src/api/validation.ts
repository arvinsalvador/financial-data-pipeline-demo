import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";

interface Page<T> { items: T[]; total: number; page: number; page_size: number; }
export interface ValidationRun { id: number; pipeline_run_id: number; validation_version: string; target_type: string; target_id: number | null; input_fingerprint: string; status: string; total_rules: number; passed_rules: number; failed_rules: number; skipped_rules: number; disabled_rules: number; total_issues: number; information_count: number; warning_count: number; error_count: number; critical_count: number; records_evaluated: number; duration_ms: number; no_op: boolean; }
export interface ValidationIssue { id: number; validation_run_id: number; validation_rule_id: number; issue_code: string; issue_type: string; severity: string; status: string; entity_type: string; entity_key: string | null; filename: string | null; row_number: number | null; column_name: string | null; message: string; observed_value: string | null; expected_value: string | null; }
export interface ValidationRule { id: number; code: string; description: string; rule_group: string; target_entity: string; severity: string; version: string; execution_order: number; is_enabled: boolean; }
export interface ValidationResult { id: number; validation_rule_id: number; status: string; records_evaluated: number; issue_count: number; duration_ms: number; details_json: Record<string, unknown> | null; }
export interface ValidationSummary { validation_run_id: number; overall_status: string; issue_count: number; counts_by_severity_json: Record<string, number>; counts_by_rule_json: Record<string, number>; counts_by_file_json: Record<string, number>; counts_by_entity_json: Record<string, number>; control_totals_json: Record<string, unknown>; summary_fingerprint: string; }
export interface ValidationStatistic { id: number; dimension_type: string; dimension_key: string; issue_count: number; records_evaluated: number; }
export interface ValidationReport { id: number; report_type: string; filename: string; relative_path: string; sha256_checksum: string; file_size_bytes: number; }

async function request<T>(path: string, init?: RequestInit): Promise<T> { const response = await governedFetch(`${API_BASE_URL}${path}`, init); const body = (await response.json()) as T & { detail?: string }; if (!response.ok) throw new Error(body.detail ?? `Request failed (${response.status})`); return body; }
export async function fetchValidationRuns() { return (await request<Page<ValidationRun>>("/validation/runs?page_size=100")).items; }
export function executeValidation(targetType: string, targetId: number | null, force: boolean) { return request<ValidationRun>("/validation/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target_type: targetType, target_id: targetId, force_rerun: force }) }); }
export async function fetchValidationIssues(runId: number, filters: Record<string, string> = {}) { const query = new URLSearchParams({ run_id: String(runId), page_size: "500", ...filters }); return (await request<Page<ValidationIssue>>(`/validation/issues?${query}`)).items; }
export function fetchValidationRules() { return request<ValidationRule[]>("/validation/rules"); }
export async function fetchValidationResults(runId: number) { return (await request<Page<ValidationResult>>(`/validation/runs/${runId}/results?page_size=100`)).items; }
export function fetchValidationSummary(runId: number) { return request<ValidationSummary>(`/validation/summary?run_id=${runId}`); }
export async function fetchValidationStatistics(runId: number) { return (await request<Page<ValidationStatistic>>(`/validation/statistics?run_id=${runId}&page_size=500`)).items; }
export async function fetchValidationReports(runId: number) { return (await request<Page<ValidationReport>>(`/validation/reports?run_id=${runId}&page_size=100`)).items; }
