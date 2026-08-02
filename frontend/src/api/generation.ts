import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";

export interface GeneratedDataset {
  id: number;
  pipeline_run_id: number;
  normalization_run_id: number | null;
  input_fingerprint: string;
  generator_version: string;
  random_seed: number;
  generation_date: string;
  status: string;
  file_count: number;
  record_count: number;
  generated_customer_count: number;
  generated_vendor_count: number;
  generated_invoice_count: number;
  generated_payment_count: number;
  generated_ap_bill_count: number;
  generated_gl_entry_count: number;
  no_op: boolean;
}
export interface CanonicalGenerationCounts {
  financial_accounts: number;
  bank_transactions: number;
  credit_card_transactions: number;
  employees: number;
  payroll_runs: number;
  payroll_entries: number;
  lineage: number;
}
export interface GenerationEligibility {
  normalization_run_id: number;
  tenant_id: number;
  status: string;
  completed_at: string | null;
  source_file_count: number;
  eligible: boolean;
  canonical_counts: CanonicalGenerationCounts;
  missing_prerequisites: string[];
  blocking_conditions: string[];
  warnings: string[];
  already_generated_run_id: number | null;
  can_force_rerun: boolean;
  input_fingerprint: string;
}
export interface GeneratedFile { id: number; file_type: string; filename: string; relative_path: string; sha256_checksum: string; file_size_bytes: number; record_count: number; column_count: number; }
export interface GenerationControl { id: number; control_name: string; expected_value: string; actual_value: string; difference: string; status: string; }
export interface GeneratedLink { id: number; generated_file_type: string; generated_record_key: string; relationship_type: string; related_entity_type: string; related_entity_id: string; }
interface Page<T> { items: T[]; total: number; page: number; page_size: number; }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await governedFetch(`${API_BASE_URL}${path}`, init);
  const body = (await response.json()) as T & { detail?: string };
  if (!response.ok) throw new Error(body.detail ?? `Request failed (${response.status})`);
  return body;
}

export async function fetchGenerationEligibility() { return (await request<{ items: GenerationEligibility[] }>("/generated-datasets/eligible-inputs")).items; }
export async function fetchGeneratedDatasets() { return (await request<Page<GeneratedDataset>>("/generated-datasets?page_size=100")).items; }
export function generateDataset(normalizationRunId: number, seed: number, generationDate: string, forceRerun = false) { return request<GeneratedDataset>("/generated-datasets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ normalization_run_id: normalizationRunId, random_seed: seed, generation_date: generationDate, force_rerun: forceRerun }) }); }
export async function fetchGeneratedFiles(runId: number) { return (await request<Page<GeneratedFile>>(`/generated-datasets/${runId}/files?page_size=100`)).items; }
export async function fetchGenerationControls(runId: number) { return (await request<Page<GenerationControl>>(`/generated-datasets/${runId}/control-totals?page_size=100`)).items; }
export async function fetchGeneratedLinks(runId: number) { return (await request<Page<GeneratedLink>>(`/generated-datasets/${runId}/links?page_size=100`)).items; }
export async function fetchGeneratedRecords(fileId: number) { return (await request<Page<Record<string, string>>>(`/generated-source-files/${fileId}/records?page_size=100`)).items; }
