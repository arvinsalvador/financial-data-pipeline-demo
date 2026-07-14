import { useEffect, useState } from "react";

import { getDemoUser, getTenantCode } from "../api/context";
import { addMember, assignMemberRole, createTenant, fetchAuditEvents, fetchMembers, fetchRoles, fetchTenants, fetchUsers, removeMemberRole, setTenantArchived, updateTenant, type AuditEvent, type Member, type Role, type Tenant, type User } from "../api/governance";

export function GovernancePage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({code: "", name: "", display_name: "", default_currency: "USD", timezone: "UTC"});
  const [editingTenantId, setEditingTenantId] = useState<number | null>(null);
  const [newMemberUserId, setNewMemberUserId] = useState(0);
  const [roleId, setRoleId] = useState(0);
  const [auditFilters, setAuditFilters] = useState({action: "", entityType: "", from: "", to: ""});
  const isAdmin = getDemoUser() === "admin@demo.local";
  const activeTenant = tenants.find((tenant) => tenant.code === getTenantCode());

  async function refresh() {
    try {
      const tenantRows = await fetchTenants();
      setTenants(tenantRows);
      const active = tenantRows.find((tenant) => tenant.code === getTenantCode());
      if (active) {
        try { setMembers(await fetchMembers(active.id)); } catch { setMembers([]); }
      }
      try { setUsers(await fetchUsers()); setRoles(await fetchRoles()); } catch { setUsers([]); setRoles([]); }
      try { setEvents(await fetchAuditEvents()); } catch { setEvents([]); }
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Governance data failed to load");
    }
  }

  useEffect(() => {
    void fetchTenants()
      .then(async (tenantRows) => {
        setTenants(tenantRows);
        const active = tenantRows.find((tenant) => tenant.code === getTenantCode());
        if (active) {
          try { setMembers(await fetchMembers(active.id)); } catch { setMembers([]); }
        }
        try { setUsers(await fetchUsers()); setRoles(await fetchRoles()); } catch { setUsers([]); setRoles([]); }
        try { setEvents(await fetchAuditEvents()); } catch { setEvents([]); }
      })
      .catch((requestError: unknown) =>
        setError(requestError instanceof Error ? requestError.message : "Governance data failed to load"),
      );
  }, []);

  async function submitTenant() {
    try {
      if (editingTenantId) await updateTenant(editingTenantId, form); else await createTenant(form);
      setEditingTenantId(null);
      setForm({code: "", name: "", display_name: "", default_currency: "USD", timezone: "UTC"});
      await refresh();
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Tenant creation failed"); }
  }

  return <section className="governance-page">
    <div className="section-heading"><div><p className="eyebrow">Phase 3 · Governance</p><h2>Tenant administration</h2><p>Development-only context; backend permissions remain authoritative.</p></div><button type="button" onClick={() => void refresh()}>Refresh</button></div>
    {error && <p className="upload-message error">{error}</p>}
    {isAdmin && <div className="governance-form"><h3>{editingTenantId ? "Edit tenant" : "Create tenant"}</h3><div className="form-grid">
      <label>Code<input value={form.code} onChange={(event) => setForm({...form, code: event.target.value})} /></label>
      <label>Name<input value={form.name} onChange={(event) => setForm({...form, name: event.target.value, display_name: event.target.value})} /></label>
      <label>Currency<input value={form.default_currency} maxLength={3} onChange={(event) => setForm({...form, default_currency: event.target.value.toUpperCase()})} /></label>
      <label>Timezone<input value={form.timezone} onChange={(event) => setForm({...form, timezone: event.target.value})} /></label>
    </div><button type="button" disabled={!form.code || !form.name} onClick={() => void submitTenant()}>{editingTenantId ? "Save tenant" : "Create tenant"}</button></div>}
    <h3>Tenants</h3><div className="table-wrap"><table><thead><tr><th>Name</th><th>Code</th><th>Status</th><th>Currency</th><th>Timezone</th><th>Created</th><th /></tr></thead><tbody>{tenants.map((tenant) => <tr key={tenant.id}><td>{tenant.display_name}</td><td>{tenant.code}</td><td>{tenant.status}</td><td>{tenant.default_currency}</td><td>{tenant.timezone}</td><td>{new Date(tenant.created_at).toLocaleDateString()}</td><td>{isAdmin && <><button className="text-button" type="button" onClick={() => {setEditingTenantId(tenant.id); setForm({code: tenant.code, name: tenant.name, display_name: tenant.display_name, default_currency: tenant.default_currency, timezone: tenant.timezone});}}>Edit</button>{" · "}<button className="text-button" type="button" onClick={() => void setTenantArchived(tenant.id, tenant.status !== "archived").then(refresh)}>{tenant.status === "archived" ? "Restore" : "Archive"}</button></>}</td></tr>)}</tbody></table></div>
    {isAdmin && <div className="filters"><label>Add member<select value={newMemberUserId} onChange={(event) => setNewMemberUserId(Number(event.target.value))}><option value={0}>Select user</option>{users.map((user) => <option key={user.id} value={user.id}>{user.display_name} · {user.email}</option>)}</select></label><button type="button" disabled={!newMemberUserId || !activeTenant} onClick={() => activeTenant && void addMember(activeTenant.id, newMemberUserId).then(refresh)}>Add member</button><label>Role<select value={roleId} onChange={(event) => setRoleId(Number(event.target.value))}><option value={0}>Select role</option>{roles.filter((role) => role.scope === "tenant").map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label></div>}
    <h3>Tenant members</h3><div className="table-wrap"><table><thead><tr><th>User</th><th>Email</th><th>Status</th><th>Roles</th><th>Joined</th><th /></tr></thead><tbody>{members.length ? members.map((member) => <tr key={member.id}><td>{member.user_display_name}</td><td>{member.user_email}</td><td>{member.status}</td><td>{member.roles.join(", ")}</td><td>{member.joined_at ? new Date(member.joined_at).toLocaleDateString() : "—"}</td><td>{isAdmin && <><button className="text-button" type="button" disabled={!roleId} onClick={() => void assignMemberRole(member.id, roleId).then(refresh)}>Assign</button>{member.roles.map((code) => {const role = roles.find((item) => item.code === code); return role ? <button key={code} className="text-button" type="button" onClick={() => void removeMemberRole(member.id, role.id).then(refresh)}>Remove {code}</button> : null;})}</>}</td></tr>) : <tr><td colSpan={6} className="empty-row">Membership details require users.view.</td></tr>}</tbody></table></div>
    <div className="filters"><label>Action<input value={auditFilters.action} onChange={(event) => setAuditFilters({...auditFilters, action: event.target.value})} /></label><label>Entity type<input value={auditFilters.entityType} onChange={(event) => setAuditFilters({...auditFilters, entityType: event.target.value})} /></label><label>From<input type="date" value={auditFilters.from} onChange={(event) => setAuditFilters({...auditFilters, from: event.target.value})} /></label><label>To<input type="date" value={auditFilters.to} onChange={(event) => setAuditFilters({...auditFilters, to: event.target.value})} /></label><button type="button" onClick={() => void fetchAuditEvents(auditFilters.action, auditFilters.entityType, auditFilters.from, auditFilters.to).then(setEvents)}>Filter audits</button></div>
    <h3>Audit log</h3><div className="table-wrap"><table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Description</th><th>Pipeline</th><th>Source</th><th>Event</th></tr></thead><tbody>{events.length ? events.map((event) => <tr key={event.id} onClick={() => setSelectedEvent(event)}><td>{new Date(event.occurred_at).toLocaleString()}</td><td>{event.actor_type} #{event.actor_user_id ?? "—"}</td><td>{event.action}</td><td>{event.entity_type} #{event.entity_id ?? "—"}</td><td>{event.description}</td><td>{event.pipeline_run_id ?? "—"}</td><td>{event.source_file_id ?? "—"}</td><td>{event.event_type}</td></tr>) : <tr><td colSpan={8} className="empty-row">Audit access requires audit_events.view.</td></tr>}</tbody></table></div>
    {selectedEvent && <aside className="detail-card"><button className="close-button" type="button" onClick={() => setSelectedEvent(null)}>Close</button><p className="eyebrow">Audit event #{selectedEvent.id}</p><h3>{selectedEvent.description}</h3><pre>{JSON.stringify({metadata: selectedEvent.metadata_json, changes: selectedEvent.changes}, null, 2)}</pre></aside>}
  </section>;
}
