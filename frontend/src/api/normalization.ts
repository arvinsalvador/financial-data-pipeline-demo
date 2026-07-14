import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";
import type { Artifact, PipelineStep } from "./ingestion";

export interface NormalizationSummary { id: number; tenant_id: number; source_file_id: number; ingestion_run_id: number; status: string; started_at: string; completed_at: string | null; staging_count: number; canonical_count: number; exception_count: number; mapping_code: string | null; mapping_version: string | null; normalization_version: string | null; no_op: boolean; error_message: string | null; steps: PipelineStep[]; artifacts: Artifact[]; }
export interface NormalizationControl { id: number; control_name: string; staging_value: string | null; canonical_value: string | null; difference_value: string | null; status: string; }
export interface NormalizationException { id: number; staging_entity_type: string; staging_entity_id: number; exception_code: string; exception_type: string; severity: string; field_name: string | null; observed_value: string | null; expected_value: string | null; message: string; status: string; created_at: string; }
interface Page<T> { items: T[]; total: number; page: number; page_size: number; }
async function request<T>(path: string, init?: RequestInit): Promise<T> { const response = await governedFetch(`${API_BASE_URL}${path}`, init); const body = (await response.json()) as T & { detail?: string }; if (!response.ok) throw new Error(body.detail ?? `Request failed (${response.status})`); return body; }
export function normalizeIngestion(ingestionRunId: number, mappingCode?: string, forceRerun = false) { return request<NormalizationSummary>(`/ingestions/${ingestionRunId}/normalize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mapping_code: mappingCode || null, force_rerun: forceRerun }) }); }
export async function fetchNormalizations(ingestionRunId: number) { return (await request<Page<NormalizationSummary>>(`/ingestions/${ingestionRunId}/normalizations`)).items; }
export function fetchNormalizationControls(runId: number) { return request<NormalizationControl[]>(`/normalizations/${runId}/control-totals`); }
export async function fetchNormalizationExceptions(runId: number) { return (await request<Page<NormalizationException>>(`/normalizations/${runId}/exceptions?page_size=200`)).items; }
export async function fetchCanonical(type: string) { return (await request<Page<Record<string, unknown>>>(`/canonical/${type}?page_size=100`)).items; }
export async function fetchCanonicalLineage(type: string, id: number) { return (await request<Page<Record<string, unknown>>>(`/canonical/${type}/${id}/lineage`)).items; }
