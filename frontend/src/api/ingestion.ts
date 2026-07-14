import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";

export interface PipelineStep {
  step_name: string; step_order: number; status: string; started_at: string;
  completed_at: string | null; metadata_json: Record<string, unknown> | null;
  error_message: string | null;
}
export interface Artifact { id: number; artifact_type: string; name: string; relative_path: string; checksum: string | null; }
export interface IngestionSummary {
  id: number; tenant_id: number; source_file_id: number; source_filename: string;
  source_system_code: string; status: string; started_at: string; completed_at: string | null;
  records_extracted: number; records_accepted: number; records_rejected: number;
  connector: string | null; mapping_code: string | null; mapping_version: string | null;
  ingestion_version: string | null; no_op: boolean; error_message: string | null;
  steps: PipelineStep[]; artifacts: Artifact[];
}
export interface RawRow { id: number; source_row_number: number; source_record_id: string | null; raw_data_json: Record<string, string | null>; raw_row_hash: string; row_status: string; created_at: string; }
export interface Rejection { id: number; raw_source_row_id: number; source_row_number: number; rejection_code: string; rejection_category: string; severity: string; field_name: string | null; observed_value: string | null; message: string; }
export interface ControlTotal { id: number; control_name: string; source_value: string | null; loaded_value: string | null; difference_value: string | null; tolerance: string | null; status: string; }
export interface MappingColumn { id: number; source_column_name: string; canonical_field_name: string; target_data_type: string; is_required: boolean; parser_name: string | null; transformation_config_json: { aliases?: string[] } | null; }
export interface Mapping { id: number; mapping_code: string; mapping_name: string; mapping_version: string; source_file_pattern: string; target_record_type: string; is_active: boolean; columns: MappingColumn[]; }
interface Page<T> { items: T[]; total: number; page: number; page_size: number; }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await governedFetch(`${API_BASE_URL}${path}`, init);
  const body = (await response.json()) as T & { detail?: string };
  if (!response.ok) throw new Error(body.detail ?? `Request failed (${response.status})`);
  return body;
}
export function ingestSourceFile(sourceFileId: number, mappingCode: string, forceRerun = false) {
  return request<IngestionSummary>(`/source-files/${sourceFileId}/ingest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mapping_code: mappingCode, force_rerun: forceRerun }) });
}
export async function fetchIngestions(sourceFileId: number) { return (await request<Page<IngestionSummary>>(`/source-files/${sourceFileId}/ingestions`)).items; }
export function fetchIngestion(id: number) { return request<IngestionSummary>(`/ingestions/${id}`); }
export async function fetchRawRows(id: number) { return (await request<Page<RawRow>>(`/ingestions/${id}/raw-rows?page_size=200`)).items; }
export async function fetchRejections(id: number, filters = "") { return (await request<Page<Rejection>>(`/ingestions/${id}/rejections?page_size=200${filters}`)).items; }
export function fetchControlTotals(id: number) { return request<ControlTotal[]>(`/ingestions/${id}/control-totals`); }
export function fetchMappings() { return request<Mapping[]>("/schema-mappings"); }
export async function fetchStaging(type: string) { return (await request<Page<Record<string, unknown>>>(`/staging/${type}?page_size=100`)).items; }
