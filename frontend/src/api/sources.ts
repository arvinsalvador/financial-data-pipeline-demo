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
