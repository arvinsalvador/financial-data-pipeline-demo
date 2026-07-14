import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";

export interface Tenant { id: number; code: string; name: string; display_name: string; status: string; default_currency: string; timezone: string; created_at: string; }
export interface Member { id: number; tenant_id: number; user_id: number; user_email: string; user_display_name: string; status: string; roles: string[]; joined_at: string | null; }
export interface User { id: number; email: string; display_name: string; status: string; }
export interface Role { id: number; code: string; name: string; scope: string; }
export interface AuditEvent { id: number; occurred_at: string; actor_user_id: number | null; actor_type: string; action: string; entity_type: string; entity_id: string | null; description: string; pipeline_run_id: number | null; source_file_id: number | null; event_type: string; metadata_json: Record<string, unknown> | null; changes: Array<{field_name: string; old_value_json: unknown; new_value_json: unknown}>; }
interface Page<T> { items: T[]; total: number; }

async function parse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as T & { detail?: string };
  if (!response.ok) throw new Error(body.detail ?? `Request failed (${response.status})`);
  return body;
}

export async function fetchTenants(): Promise<Tenant[]> { return parse<Tenant[]>(await governedFetch(`${API_BASE_URL}/tenants`)); }
export async function createTenant(values: Omit<Tenant, "id" | "created_at" | "status">): Promise<Tenant> {
  return parse<Tenant>(await governedFetch(`${API_BASE_URL}/tenants`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...values, status: "active", fiscal_year_start_month: 1}) }));
}
export async function updateTenant(id: number, values: Partial<Tenant>): Promise<Tenant> { return parse<Tenant>(await governedFetch(`${API_BASE_URL}/tenants/${id}`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)})); }
export async function setTenantArchived(id: number, archive: boolean): Promise<Tenant> { return parse<Tenant>(await governedFetch(`${API_BASE_URL}/tenants/${id}/${archive ? "archive" : "restore"}`, {method: "POST"})); }
export async function fetchMembers(tenantId: number): Promise<Member[]> { return parse<Member[]>(await governedFetch(`${API_BASE_URL}/tenants/${tenantId}/members`)); }
export async function fetchUsers(): Promise<User[]> { return parse<User[]>(await governedFetch(`${API_BASE_URL}/users`)); }
export async function fetchRoles(): Promise<Role[]> { return parse<Role[]>(await governedFetch(`${API_BASE_URL}/roles`)); }
export async function addMember(tenantId: number, userId: number): Promise<Member> { return parse<Member>(await governedFetch(`${API_BASE_URL}/tenants/${tenantId}/members`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({user_id: userId, status: "active"})})); }
export async function assignMemberRole(membershipId: number, roleId: number): Promise<void> { const response = await governedFetch(`${API_BASE_URL}/tenant-memberships/${membershipId}/roles`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({role_id: roleId})}); if (!response.ok) throw new Error(`Request failed (${response.status})`); }
export async function removeMemberRole(membershipId: number, roleId: number): Promise<void> { const response = await governedFetch(`${API_BASE_URL}/tenant-memberships/${membershipId}/roles/${roleId}`, {method: "DELETE"}); if (!response.ok) throw new Error(`Request failed (${response.status})`); }
export async function fetchAuditEvents(action = "", entityType = "", occurredFrom = "", occurredTo = ""): Promise<AuditEvent[]> {
  const params = new URLSearchParams({page_size: "100"}); if (action) params.set("action", action); if (entityType) params.set("entity_type", entityType); if (occurredFrom) params.set("occurred_from", new Date(occurredFrom).toISOString()); if (occurredTo) params.set("occurred_to", new Date(`${occurredTo}T23:59:59`).toISOString());
  return (await parse<Page<AuditEvent>>(await governedFetch(`${API_BASE_URL}/audit-events?${params}`))).items;
}
