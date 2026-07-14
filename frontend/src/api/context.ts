export const DEFAULT_TENANT = "demo_coffee_group";
export const DEFAULT_ACTOR = "analyst@demo.local";

export function getTenantCode() {
  return localStorage.getItem("demoTenantCode") ?? DEFAULT_TENANT;
}

export function getDemoUser() {
  return localStorage.getItem("demoActorEmail") ?? DEFAULT_ACTOR;
}

export function setDevelopmentContext(tenantCode: string, actorEmail: string) {
  localStorage.setItem("demoTenantCode", tenantCode);
  localStorage.setItem("demoActorEmail", actorEmail);
}

export function governedFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("X-Tenant-Code", getTenantCode());
  headers.set("X-Demo-User", getDemoUser());
  return fetch(input, { ...init, headers });
}
