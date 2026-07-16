from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext
from app.core.config import Settings
from app.models import (
    AuditEvent,
    Permission,
    PipelineDefinition,
    PipelineRun,
    Role,
    SourceFile,
    SourceSystem,
    Tenant,
    User,
)
from app.services.governance import PipelineArtifactService

ADMIN = {"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": "admin@demo.local"}
ANALYST = {"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": "analyst@demo.local"}
VIEWER = {"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": "viewer@demo.local"}


def upload(client: TestClient, headers: dict[str, str], content: bytes) -> object:
    return client.post(
        "/api/v1/source-files/upload",
        headers=headers,
        files={"file": (f"{uuid4().hex}.csv", content, "text/csv")},
        data={"source_system_code": "kaggle_small_business_finance"},
    )


def test_governance_seed_contains_demo_entities(client: TestClient, db_session: Session) -> None:
    assert db_session.scalar(select(func.count()).select_from(Role)) == 4
    assert (db_session.scalar(select(func.count()).select_from(Permission)) or 0) >= 19
    assert (
        db_session.scalar(
            select(func.count()).select_from(User).where(User.email.endswith("@demo.local"))
        )
        == 4
    )
    assert db_session.scalar(select(func.count()).select_from(PipelineDefinition)) == 10
    tenants = client.get("/api/v1/tenants", headers=ADMIN)
    assert tenants.status_code == 200
    assert any(item["code"] == "demo_coffee_group" for item in tenants.json())


def test_missing_context_and_viewer_permissions(client: TestClient) -> None:
    no_tenant = client.get("/api/v1/source-files", headers={"X-Tenant-Code": ""})
    no_actor = client.get("/api/v1/source-files", headers={"X-Demo-User": ""})
    assert no_tenant.status_code == 400
    assert no_actor.status_code == 401
    assert client.get("/api/v1/source-files", headers=VIEWER).status_code == 200
    assert upload(client, VIEWER, b"id,amount\na,1\n").status_code == 403


def test_tenant_create_archive_restore_and_inactive_context(client: TestClient) -> None:
    code = f"tenant_{uuid4().hex[:10]}"
    created = client.post(
        "/api/v1/tenants",
        headers=ADMIN,
        json={
            "code": code,
            "name": "Test Tenant",
            "display_name": "Test Tenant",
            "default_currency": "USD",
            "timezone": "UTC",
        },
    )
    assert created.status_code == 201
    tenant_id = created.json()["id"]
    duplicate = client.post(
        "/api/v1/tenants",
        headers=ADMIN,
        json={
            "code": code,
            "name": "Duplicate",
            "display_name": "Duplicate",
            "default_currency": "USD",
            "timezone": "UTC",
        },
    )
    assert duplicate.status_code == 409
    archived = client.post(f"/api/v1/tenants/{tenant_id}/archive", headers=ADMIN)
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    inactive = client.get(
        "/api/v1/source-files", headers={"X-Tenant-Code": code, "X-Demo-User": "admin@demo.local"}
    )
    assert inactive.status_code == 403
    restored = client.post(f"/api/v1/tenants/{tenant_id}/restore", headers=ADMIN)
    assert restored.status_code == 200 and restored.json()["status"] == "active"


def test_user_normalization_plaintext_rejection_and_membership_roles(client: TestClient) -> None:
    email = f"Person-{uuid4().hex[:8]}@Example.COM"
    created = client.post(
        "/api/v1/users",
        headers=ADMIN,
        json={"email": email, "display_name": "Test Person", "status": "active"},
    )
    assert created.status_code == 201
    assert created.json()["email"] == email.lower()
    assert "password" not in created.json() and "password_hash" not in created.json()
    rejected = client.post(
        "/api/v1/users",
        headers=ADMIN,
        json={
            "email": f"x-{uuid4().hex}@example.com",
            "display_name": "Unsafe",
            "password": "plaintext",
        },
    )
    assert rejected.status_code == 422
    duplicate = client.post(
        "/api/v1/users",
        headers=ADMIN,
        json={"email": email.swapcase(), "display_name": "Duplicate"},
    )
    assert duplicate.status_code == 409
    tenant_id = client.get("/api/v1/tenants", headers=ADMIN).json()[0]["id"]
    membership = client.post(
        f"/api/v1/tenants/{tenant_id}/members",
        headers=ADMIN,
        json={"user_id": created.json()["id"], "status": "active"},
    )
    assert membership.status_code == 201
    duplicate_membership = client.post(
        f"/api/v1/tenants/{tenant_id}/members",
        headers=ADMIN,
        json={"user_id": created.json()["id"], "status": "active"},
    )
    assert duplicate_membership.status_code == 409
    role = next(
        item
        for item in client.get("/api/v1/roles", headers=ADMIN).json()
        if item["code"] == "client_viewer"
    )
    assigned = client.post(
        f"/api/v1/tenant-memberships/{membership.json()['id']}/roles",
        headers=ADMIN,
        json={"role_id": role["id"]},
    )
    assert assigned.status_code == 204
    assert (
        client.post(
            f"/api/v1/tenant-memberships/{membership.json()['id']}/roles",
            headers=ADMIN,
            json={"role_id": role["id"]},
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/tenant-memberships/{membership.json()['id']}/roles/{role['id']}",
            headers=ADMIN,
        ).status_code
        == 204
    )
    suspended = client.patch(
        f"/api/v1/tenant-memberships/{membership.json()['id']}",
        headers=ADMIN,
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200 and suspended.json()["status"] == "suspended"
    blocked = client.get(
        "/api/v1/source-files",
        headers={"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": email.lower()},
    )
    assert blocked.status_code == 403


def test_cross_tenant_isolation_checksum_scope_audit_and_artifacts(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    code = f"isolation_{uuid4().hex[:10]}"
    tenant_response = client.post(
        "/api/v1/tenants",
        headers=ADMIN,
        json={
            "code": code,
            "name": "Isolation Tenant",
            "display_name": "Isolation Tenant",
            "default_currency": "USD",
            "timezone": "UTC",
        },
    )
    tenant_id = tenant_response.json()["id"]
    db_session.add(
        SourceSystem(
            tenant_id=tenant_id,
            code="kaggle_small_business_finance",
            name="Isolation CSV",
            description=None,
            source_type="csv",
            is_active=True,
        )
    )
    db_session.commit()
    tenant_headers = {"X-Tenant-Code": code, "X-Demo-User": "admin@demo.local"}
    content = f"id,amount\n{uuid4().hex},10\n".encode()
    tenant_b_upload = upload(client, tenant_headers, content)
    tenant_a_upload = upload(client, ADMIN, content)
    assert tenant_b_upload.status_code == tenant_a_upload.status_code == 201
    source_b = tenant_b_upload.json()["source_file_id"]
    assert client.get(f"/api/v1/source-files/{source_b}", headers=ADMIN).status_code == 404
    assert (
        client.get(
            f"/api/v1/source-files/{source_b}?tenant_id={tenant_id}", headers=ADMIN
        ).status_code
        == 404
    )
    assert all(
        item["id"] != source_b
        for item in client.get("/api/v1/source-files", headers=ADMIN).json()["items"]
    )
    profile_b = client.post(f"/api/v1/source-files/{source_b}/profile", headers=tenant_headers)
    assert profile_b.status_code == 200
    assert (
        client.get(f"/api/v1/profiles/{profile_b.json()['id']}", headers=ADMIN).status_code == 404
    )
    assert (
        client.get(
            f"/api/v1/pipeline-runs/{profile_b.json()['pipeline_run_id']}", headers=ADMIN
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/profiles/{profile_b.json()['id']}/issues", headers=ADMIN).status_code
        == 404
    )
    run = db_session.get(PipelineRun, profile_b.json()["pipeline_run_id"])
    tenant = db_session.get(Tenant, tenant_id)
    admin = db_session.scalar(select(User).where(User.email == "admin@demo.local"))
    assert (
        run is not None
        and tenant is not None
        and admin is not None
        and run.pipeline_definition_id is not None
    )
    context = RequestContext(tenant, admin, frozenset({"*"}), frozenset({"platform_admin"}))
    artifact = PipelineArtifactService().register(
        db_session,
        context,
        run,
        {
            "artifact_type": "validation_report",
            "name": "report.json",
            "relative_path": "reports/report.json",
            "checksum": "a" * 64,
            "mime_type": "application/json",
            "file_size_bytes": 10,
            "metadata_json": {},
        },
    )
    assert artifact.checksum == "a" * 64 and not Path(artifact.relative_path).is_absolute()
    try:
        PipelineArtifactService().register(
            db_session,
            context,
            run,
            {
                "artifact_type": "validation_report",
                "name": "unsafe.json",
                "relative_path": "../unsafe.json",
            },
        )
    except ValueError as error:
        assert "relative" in str(error)
    else:
        raise AssertionError("Unsafe artifact path was accepted")
    assert client.get(f"/api/v1/pipeline-artifacts/{artifact.id}", headers=ADMIN).status_code == 404
    assert (
        client.get(f"/api/v1/pipeline-artifacts/{artifact.id}", headers=tenant_headers).status_code
        == 200
    )
    demo_audits = client.get(
        "/api/v1/audit-events", headers={**ANALYST, "X-Demo-User": "cfo@demo.local"}
    ).json()["items"]
    assert all(item["tenant_id"] != tenant_id for item in demo_audits)
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        )
        >= 2
    )
    audit_id = db_session.scalar(
        select(AuditEvent.id).where(AuditEvent.tenant_id == tenant_id).limit(1)
    )
    assert audit_id is not None
    assert (
        client.patch(f"/api/v1/audit-events/{audit_id}", headers=tenant_headers).status_code == 405
    )
    assert (
        client.delete(f"/api/v1/audit-events/{audit_id}", headers=tenant_headers).status_code == 405
    )
    stored_b = db_session.get(SourceFile, source_b)
    assert (
        stored_b is not None
        and (test_settings.REGISTERED_RAW_DIRECTORY / stored_b.stored_filename).is_file()
    )
