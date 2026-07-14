from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    Permission,
    PipelineDefinition,
    Role,
    RolePermission,
    Tenant,
    TenantUser,
    TenantUserRole,
    User,
)

PERMISSIONS = (
    "tenants.view",
    "tenants.manage",
    "users.view",
    "users.manage",
    "roles.view",
    "roles.manage",
    "source_systems.view",
    "source_systems.manage",
    "source_files.view",
    "source_files.upload",
    "source_files.profile",
    "profiles.view",
    "data_quality_issues.view",
    "data_quality_issues.manage",
    "pipeline_runs.view",
    "pipeline_runs.execute",
    "pipeline_runs.retry",
    "audit_events.view",
    "dashboards.view",
    "source_files.ingest",
    "raw_rows.view",
    "rejected_rows.view",
    "staging_records.view",
    "ingestion_control_totals.view",
    "normalization.execute",
    "canonical_records.view",
    "canonical_lineage.view",
    "normalization_exceptions.view",
    "normalization_exceptions.manage",
    "normalization_control_totals.view",
    "generated_datasets.execute",
    "generated_datasets.view",
    "generated_files.view",
    "generated_links.view",
    "generation_controls.view",
    "generation_exceptions.view",
    "messy_datasets.execute",
    "messy_datasets.view",
    "defect_scenarios.view",
    "data_mutations.view",
    "expected_exceptions.view",
    "messy_controls.view",
    "validation.execute",
    "validation.runs.view",
    "validation.issues.view",
    "validation.rules.view",
    "validation.reports.view",
    "validation.statistics.view",
)
ROLE_PERMISSIONS = {
    "platform_admin": PERMISSIONS,
    "cfo_user": (
        "users.view",
        "roles.view",
        "source_systems.view",
        "source_files.view",
        "source_files.upload",
        "source_files.profile",
        "profiles.view",
        "data_quality_issues.view",
        "data_quality_issues.manage",
        "pipeline_runs.view",
        "pipeline_runs.execute",
        "pipeline_runs.retry",
        "audit_events.view",
        "dashboards.view",
        "source_files.ingest",
        "raw_rows.view",
        "rejected_rows.view",
        "staging_records.view",
        "ingestion_control_totals.view",
        "normalization.execute",
        "canonical_records.view",
        "canonical_lineage.view",
        "normalization_exceptions.view",
        "normalization_exceptions.manage",
        "normalization_control_totals.view",
        "generated_datasets.execute",
        "generated_datasets.view",
        "generated_files.view",
        "generated_links.view",
        "generation_controls.view",
        "generation_exceptions.view",
        "messy_datasets.execute",
        "messy_datasets.view",
        "defect_scenarios.view",
        "data_mutations.view",
        "expected_exceptions.view",
        "messy_controls.view",
        "validation.execute",
        "validation.runs.view",
        "validation.issues.view",
        "validation.rules.view",
        "validation.reports.view",
        "validation.statistics.view",
    ),
    "finance_analyst": (
        "source_systems.view",
        "source_files.view",
        "source_files.upload",
        "source_files.profile",
        "profiles.view",
        "data_quality_issues.view",
        "pipeline_runs.view",
        "pipeline_runs.execute",
        "dashboards.view",
        "source_files.ingest",
        "raw_rows.view",
        "rejected_rows.view",
        "staging_records.view",
        "ingestion_control_totals.view",
        "normalization.execute",
        "canonical_records.view",
        "canonical_lineage.view",
        "normalization_exceptions.view",
        "normalization_control_totals.view",
        "generated_datasets.execute",
        "generated_datasets.view",
        "generated_files.view",
        "generated_links.view",
        "generation_controls.view",
        "generation_exceptions.view",
        "messy_datasets.execute",
        "messy_datasets.view",
        "defect_scenarios.view",
        "data_mutations.view",
        "expected_exceptions.view",
        "messy_controls.view",
        "validation.execute",
        "validation.runs.view",
        "validation.issues.view",
        "validation.rules.view",
        "validation.reports.view",
        "validation.statistics.view",
    ),
    "client_viewer": (
        "source_systems.view",
        "source_files.view",
        "profiles.view",
        "data_quality_issues.view",
        "pipeline_runs.view",
        "dashboards.view",
        "canonical_records.view",
        "generated_datasets.view",
        "generated_files.view",
        "messy_datasets.view",
        "expected_exceptions.view",
        "validation.runs.view",
        "validation.issues.view",
        "validation.rules.view",
        "validation.reports.view",
        "validation.statistics.view",
    ),
}


def seed_governance_data(session: Session, settings: Settings) -> dict[str, int]:
    if not settings.demo_actor_headers_enabled:
        raise RuntimeError("Development governance users cannot be seeded in this environment")
    tenant = session.scalar(select(Tenant).where(Tenant.code == "demo_coffee_group"))
    if tenant is None:
        tenant = Tenant(
            code="demo_coffee_group",
            name="Demo Coffee Group",
            display_name="Demo Coffee Group",
            status="active",
            default_currency="USD",
            timezone="America/New_York",
            fiscal_year_start_month=1,
        )
        session.add(tenant)
        session.flush()
    roles: dict[str, Role] = {}
    for code, name, scope in (
        ("platform_admin", "Platform Administrator", "platform"),
        ("cfo_user", "CFO User", "tenant"),
        ("finance_analyst", "Finance Analyst", "tenant"),
        ("client_viewer", "Client Viewer", "tenant"),
    ):
        role = session.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=name, scope=scope, is_system_role=True)
            session.add(role)
            session.flush()
        roles[code] = role
    permissions: dict[str, Permission] = {}
    for code in PERMISSIONS:
        permission = session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, name=code.replace(".", " ").title())
            session.add(permission)
            session.flush()
        permissions[code] = permission
    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        for permission_code in permission_codes:
            role, permission = roles[role_code], permissions[permission_code]
            if (
                session.scalar(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == permission.id,
                    )
                )
                is None
            ):
                session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    users: dict[str, User] = {}
    for email, display_name, platform_admin in (
        ("admin@demo.local", "Demo Platform Administrator", True),
        ("cfo@demo.local", "Demo CFO User", False),
        ("analyst@demo.local", "Demo Finance Analyst", False),
        ("viewer@demo.local", "Demo Client Viewer", False),
    ):
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name=display_name,
                status="active",
                password_hash=None,
                is_platform_admin=platform_admin,
            )
            session.add(user)
            session.flush()
        else:
            user.status, user.password_hash, user.is_platform_admin = "active", None, platform_admin
        users[email] = user
    for email, role_code in (
        ("cfo@demo.local", "cfo_user"),
        ("analyst@demo.local", "finance_analyst"),
        ("viewer@demo.local", "client_viewer"),
    ):
        user = users[email]
        membership = session.scalar(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant.id, TenantUser.user_id == user.id
            )
        )
        if membership is None:
            membership = TenantUser(
                tenant_id=tenant.id, user_id=user.id, status="active", joined_at=datetime.now(UTC)
            )
            session.add(membership)
            session.flush()
        else:
            membership.status = "active"
        role = roles[role_code]
        if (
            session.scalar(
                select(TenantUserRole).where(
                    TenantUserRole.tenant_user_id == membership.id,
                    TenantUserRole.role_id == role.id,
                )
            )
            is None
        ):
            session.add(
                TenantUserRole(
                    tenant_user_id=membership.id, role_id=role.id, assigned_at=datetime.now(UTC)
                )
            )
    for code, name in (
        ("source_file_registration", "Source File Registration"),
        ("csv_profile", "CSV Profile"),
    ):
        if (
            session.scalar(
                select(PipelineDefinition).where(
                    PipelineDefinition.code == code, PipelineDefinition.version == "1.0.0"
                )
            )
            is None
        ):
            session.add(
                PipelineDefinition(
                    code=code,
                    name=name,
                    version="1.0.0",
                    is_active=True,
                    configuration_schema_json={},
                )
            )
    session.commit()
    from app.services.ingestion_seed import seed_ingestion_data

    seed_ingestion_data(session)
    from app.services.canonical_seed import seed_canonical_data

    seed_canonical_data(session)
    from app.services.messy_seed import seed_messy_data

    seed_messy_data(session)
    from app.services.validation_seed import seed_validation_data

    seed_validation_data(session)
    return {
        "tenants": 1,
        "users": len(users),
        "roles": len(roles),
        "permissions": len(permissions),
        "pipeline_definitions": 2,
    }
