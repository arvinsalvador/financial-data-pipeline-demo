import { API_BASE_URL } from "./health";

export interface SourceSystem {
  id: number;
  code: string;
  name: string;
  description: string | null;
  source_type: string;
  is_active: boolean;
}

export interface SourceFile {
  id: number;
  source_system_id: number;
  source_system_code: string;
  original_filename: string;
  stored_filename: string;
  relative_path: string;
  file_extension: string;
  mime_type: string;
  file_size_bytes: number;
  sha256_checksum: string;
  status: string;
  registered_at: string;
}

interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface SourceFileProfile {
  id: number;
  source_file_id: number;
  pipeline_run_id: number;
  profile_version: string;
  status: string;
  encoding: string | null;
  delimiter: string | null;
  row_count: number;
  column_count: number;
  empty_row_count: number;
  duplicate_row_count: number;
  file_size_bytes: number;
  date_range_start: string | null;
  date_range_end: string | null;
  total_null_count: number;
  monetary_total: string | null;
  debit_total: string | null;
  credit_total: string | null;
  opening_balance: string | null;
  closing_balance: string | null;
  calculated_closing_balance: string | null;
  running_balance_valid: boolean | null;
  generated_at: string;
  issue_totals: Record<string, number>;
}

export interface ColumnProfile {
  id: number;
  column_name: string;
  inferred_data_type: string;
  null_count: number;
  null_percentage: string;
  unique_count: number;
  minimum_value: string | null;
  maximum_value: string | null;
  earliest_date: string | null;
  latest_date: string | null;
  sample_values_json: string[] | null;
}

export interface DataQualityIssue {
  id: number;
  severity: string;
  issue_code: string;
  issue_type: string;
  column_name: string | null;
  row_number: number | null;
  message: string;
  observed_value: string | null;
  status: string;
}

export interface UploadResult {
  status: "registered" | "duplicate" | "validation_error" | "failed";
  message?: string;
  source_file_id?: number;
  existing_source_file_id?: number;
  original_filename?: string;
  stored_filename?: string;
  sha256_checksum?: string;
  file_size_bytes?: number;
  pipeline_run_id?: number;
  code?: string;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as T;
  if (!response.ok) {
    const failure = body as UploadResult;
    throw new Error(failure.message ?? `Request failed with status ${response.status}`);
  }
  return body;
}

export async function fetchSourceSystems(signal?: AbortSignal): Promise<SourceSystem[]> {
  const response = await fetch(`${API_BASE_URL}/source-systems?page_size=100`, { signal });
  return (await parseResponse<Page<SourceSystem>>(response)).items;
}

export async function fetchSourceFiles(signal?: AbortSignal): Promise<SourceFile[]> {
  const response = await fetch(`${API_BASE_URL}/source-files?page_size=20`, { signal });
  return (await parseResponse<Page<SourceFile>>(response)).items;
}

export async function fetchSourceFile(sourceFileId: number): Promise<SourceFile> {
  const response = await fetch(`${API_BASE_URL}/source-files/${sourceFileId}`);
  return parseResponse<SourceFile>(response);
}

export async function uploadSourceFile(
  file: File,
  sourceSystemCode: string,
): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source_system_code", sourceSystemCode);
  const response = await fetch(`${API_BASE_URL}/source-files/upload`, {
    method: "POST",
    body: formData,
  });
  return parseResponse<UploadResult>(response);
}

export async function profileSourceFile(sourceFileId: number): Promise<SourceFileProfile> {
  const response = await fetch(`${API_BASE_URL}/source-files/${sourceFileId}/profile`, {
    method: "POST",
  });
  return parseResponse<SourceFileProfile>(response);
}

export async function fetchLatestProfile(sourceFileId: number): Promise<SourceFileProfile> {
  const response = await fetch(`${API_BASE_URL}/source-files/${sourceFileId}/profiles/latest`);
  return parseResponse<SourceFileProfile>(response);
}

export async function fetchProfileColumns(profileId: number): Promise<ColumnProfile[]> {
  const response = await fetch(`${API_BASE_URL}/profiles/${profileId}/columns?page_size=200`);
  return (await parseResponse<Page<ColumnProfile>>(response)).items;
}

export async function fetchProfileIssues(
  profileId: number,
  severity = "",
  issueType = "",
): Promise<DataQualityIssue[]> {
  const params = new URLSearchParams({ page_size: "200" });
  if (severity) params.set("severity", severity);
  if (issueType) params.set("issue_type", issueType);
  const response = await fetch(`${API_BASE_URL}/profiles/${profileId}/issues?${params}`);
  return (await parseResponse<Page<DataQualityIssue>>(response)).items;
}
