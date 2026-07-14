# Phase 3: tenant and pipeline governance

## Architecture

Phase 3 assigns every top-level business record to a tenant before canonical ingestion.
`source_systems`, `source_files`, profiles, issues, and pipeline runs contain validated
tenant ownership. Nested column profiles and run steps derive ownership through their
parent. Queries retrieve records using both ID and tenant ID; guessed cross-tenant IDs
return 404 and query-string tenant IDs never override the validated request context.

Platform users and tenant users are distinct. A platform administrator uses
`User.is_platform_admin`; tenant users require an active `TenantUser` membership and one
or more tenant-scoped roles. Permissions are resolved centrally by
`require_permission(...)`, not embedded as frontend security rules. System roles are
`platform_admin`, `cfo_user`, `finance_analyst`, and `client_viewer`.

## Temporary development context

Local requests use these headers:

```bash
curl -H 'X-Tenant-Code: demo_coffee_group' \
  -H 'X-Demo-User: analyst@demo.local' \
  http://localhost:8000/api/v1/source-files
```

These headers are **not authentication**. They are untrusted development selectors and
must not be enabled in production. `ENABLE_DEMO_ACTOR_HEADERS` is honored only when
`ENVIRONMENT` is `development` or `test`. JWT/SSO and production identity verification
are planned for a later phase.

The React header labels this boundary explicitly, persists tenant and demo-user choices
in local storage, sends both headers centrally, and refreshes tenant-scoped views after a
switch. React may hide viewer actions, but FastAPI remains the security boundary.

Viewer upload failure example:

```bash
curl -i -X POST -H 'X-Tenant-Code: demo_coffee_group' \
  -H 'X-Demo-User: viewer@demo.local' \
  -F source_system_code=kaggle_small_business_finance -F file=@sample.csv \
  http://localhost:8000/api/v1/source-files/upload
# HTTP 403: Permission required: source_files.upload
```

## Audit and pipeline governance

Audit events are append-only business history: who caused an upload, profile, tenant or
membership change, and why. Field changes are stored separately with sensitive field
names redacted and large values bounded. No update or delete audit APIs exist. Pipeline
runs remain technical execution history with step status and errors; audit events link the
actor and business action without duplicating step logs.

`pipeline_definitions` formalizes `source_file_registration` and `csv_profile` at version
`1.0.0`. Every new run references an active definition. `pipeline_run_artifacts` tracks
registered sources and future reports using tenant ownership, SHA-256 where applicable,
and relative paths only.

## Demo seed and CLI

The migration idempotently establishes Demo Coffee Group and development-only users:
`admin@demo.local`, `cfo@demo.local`, `analyst@demo.local`, and `viewer@demo.local`. No
passwords are created.

```bash
docker compose exec backend python -m app.cli.seed_governance
docker compose exec backend python -m app.cli.list_tenants
docker compose exec backend python -m app.cli.list_demo_users
docker compose exec backend python -m app.cli.verify_tenant_integrity
```

The integrity command checks missing ownership, inactive-tenant references, duplicate
tenant-scoped codes/checksums, invalid memberships or role assignments, and missing audit
tenant context. It exits non-zero for critical findings.

## API surface

Governance APIs cover tenant create/update/archive/restore, users, memberships and role
assignments, seed-controlled roles and permissions, audit queries, pipeline definitions,
and tenant-scoped pipeline artifacts. Existing source, profile, issue, and pipeline APIs
now require validated tenant and actor context plus their mapped permission.

## Known limitations

There is no real login, password flow, JWT, SSO, tenant invitation delivery, custom-role
editor, database row-level security, or production identity provider. Demo headers must
never be treated as secure. Audit immutability is enforced through service/API design;
database-level immutable triggers can be added with the production security phase.
