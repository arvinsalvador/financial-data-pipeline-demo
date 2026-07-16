from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    ExceptionResolutionCode,
    ExceptionServiceLevelPolicy,
    ExceptionWorkflowRule,
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
    "bank_ledger_reconciliation.execute",
    "bank_ledger_reconciliation.view",
    "bank_ledger_reconciliation.review",
    "reconciliation_candidates.view",
    "reconciliation_exceptions.view",
    "reconciliation_controls.view",
    "reconciliation_reports.view",
    "payroll_reconciliation.execute",
    "payroll_reconciliation.view",
    "payroll_reconciliation.review",
    "payroll_reconciliation_candidates.view",
    "payroll_reconciliation_exceptions.view",
    "payroll_reconciliation_controls.view",
    "payroll_reconciliation_reports.view",
    "invoice_collections_reconciliation.execute",
    "invoice_collections_reconciliation.view",
    "invoice_collections_reconciliation.review",
    "invoice_collections_candidates.view",
    "invoice_collections_exceptions.view",
    "invoice_collections_controls.view",
    "invoice_collections_reports.view",
    "accounts_receivable_aging.view",
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
        "bank_ledger_reconciliation.execute",
        "bank_ledger_reconciliation.view",
        "bank_ledger_reconciliation.review",
        "reconciliation_candidates.view",
        "reconciliation_exceptions.view",
        "reconciliation_controls.view",
        "reconciliation_reports.view",
        "payroll_reconciliation.execute",
        "payroll_reconciliation.view",
        "payroll_reconciliation.review",
        "payroll_reconciliation_candidates.view",
        "payroll_reconciliation_exceptions.view",
        "payroll_reconciliation_controls.view",
        "payroll_reconciliation_reports.view",
        "invoice_collections_reconciliation.execute",
        "invoice_collections_reconciliation.view",
        "invoice_collections_reconciliation.review",
        "invoice_collections_candidates.view",
        "invoice_collections_exceptions.view",
        "invoice_collections_controls.view",
        "invoice_collections_reports.view",
        "accounts_receivable_aging.view",
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
        "bank_ledger_reconciliation.execute",
        "bank_ledger_reconciliation.view",
        "bank_ledger_reconciliation.review",
        "reconciliation_candidates.view",
        "reconciliation_exceptions.view",
        "reconciliation_controls.view",
        "reconciliation_reports.view",
        "payroll_reconciliation.execute",
        "payroll_reconciliation.view",
        "payroll_reconciliation.review",
        "payroll_reconciliation_candidates.view",
        "payroll_reconciliation_exceptions.view",
        "payroll_reconciliation_controls.view",
        "payroll_reconciliation_reports.view",
        "invoice_collections_reconciliation.execute",
        "invoice_collections_reconciliation.view",
        "invoice_collections_reconciliation.review",
        "invoice_collections_candidates.view",
        "invoice_collections_exceptions.view",
        "invoice_collections_controls.view",
        "invoice_collections_reports.view",
        "accounts_receivable_aging.view",
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
        "bank_ledger_reconciliation.view",
        "payroll_reconciliation.view",
        "invoice_collections_reconciliation.view",
        "accounts_receivable_aging.view",
    ),
}

EXCEPTION_PERMISSIONS = (
    "exceptions.synchronize",
    "exceptions.view",
    "exceptions.view_sensitive",
    "exceptions.assign",
    "exceptions.comment",
    "exceptions.review",
    "exceptions.resolve",
    "exceptions.ignore",
    "exceptions.ignore_critical",
    "exceptions.escalate",
    "exceptions.reopen",
    "exceptions.close",
    "exceptions.bulk_manage",
    "exceptions.relations_manage",
    "exceptions.evidence_manage",
    "exceptions.saved_views_manage",
    "exceptions.statistics_view",
    "exceptions.reports_view",
)
PERMISSIONS = PERMISSIONS + EXCEPTION_PERMISSIONS
ROLE_PERMISSIONS["platform_admin"] = PERMISSIONS
ROLE_PERMISSIONS["cfo_user"] = ROLE_PERMISSIONS["cfo_user"] + EXCEPTION_PERMISSIONS
ROLE_PERMISSIONS["finance_analyst"] = ROLE_PERMISSIONS["finance_analyst"] + tuple(
    code for code in EXCEPTION_PERMISSIONS if code not in {"exceptions.ignore_critical", "exceptions.close", "exceptions.view_sensitive"}
)
ROLE_PERMISSIONS["client_viewer"] = ROLE_PERMISSIONS["client_viewer"] + ("exceptions.view", "exceptions.statistics_view")

WORKFLOW_RULES = (
    ("critical_auto_escalate", "Critical Auto Escalate", None, None, "critical", "urgent", "escalated", "platform_admin", 1, True),
    ("control_total_high_priority", "Control Total High Priority", "control_totals", None, None, "high", "open", "finance_analyst", 2, True),
    ("duplicate_normal_priority", "Duplicate Normal Priority", None, "duplicate", None, "normal", "open", "finance_analyst", 3, True),
    ("warning_default_normal", "Warning Default Normal", None, None, "warning", "normal", "open", "finance_analyst", 4, True),
    ("info_default_low", "Info Default Low", None, None, "info", "low", "open", "finance_analyst", 5, False),
    ("resolved_redetection_reopens", "Resolved Redetection Reopens", None, None, None, "normal", "open", "finance_analyst", 6, True),
    ("ignored_redetection_remains_ignored_with_occurrence_increment", "Ignored Redetection Remains Ignored", None, None, None, "normal", "open", "finance_analyst", 7, False),
    ("pipeline_failure_assign_platform_admin", "Pipeline Failure Assign Platform Admin", "pipeline", None, None, "urgent", "open", "platform_admin", 8, True),
    ("reconciliation_exception_assign_finance_analyst", "Reconciliation Exception Assign Finance Analyst", None, "reconciliation", None, "high", "open", "finance_analyst", 9, True),
)
SLA_POLICIES = (
    ("info", "Info", "info", 72, 336, 336),
    ("warning", "Warning", "warning", 48, 168, 168),
    ("error", "Error", "error", 24, 72, 72),
    ("critical", "Critical", "critical", 4, 24, 24),
)
RESOLUTION_CODES = (
    "corrected_source_data", "accepted_valid_variance", "accepted_timing_difference",
    "duplicate_record_confirmed", "reversal_confirmed", "mapping_updated",
    "source_record_excluded", "manual_match_confirmed", "customer_credit_confirmed",
    "unapplied_payment_confirmed", "payroll_difference_confirmed", "false_positive",
    "expected_test_defect", "no_action_required", "deferred", "other",
)

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
        ("exception_management", "Unified Exception Management"),
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

    for index, (code, name, source_module, pattern, severity, priority, status, team, order, reopen) in enumerate(WORKFLOW_RULES, 1):
        if session.scalar(select(ExceptionWorkflowRule).where(ExceptionWorkflowRule.tenant_id == tenant.id, ExceptionWorkflowRule.code == code, ExceptionWorkflowRule.version == "1.0.0")) is None:
            session.add(ExceptionWorkflowRule(tenant_id=tenant.id, code=code, name=name, description=name, source_module=source_module, exception_code_pattern=pattern, severity=severity, initial_priority=priority, initial_status=status, auto_assign_team_code=team, escalation_after_hours=24 if priority in {"high", "urgent"} else None, resolution_requires_comment=True, ignore_requires_comment=True, reopen_on_redetection=reopen, configuration_json={}, version="1.0.0", execution_order=order, is_active=True))
    for code, name, severity, response, resolution, escalation in SLA_POLICIES:
        if session.scalar(select(ExceptionServiceLevelPolicy).where(ExceptionServiceLevelPolicy.tenant_id == tenant.id, ExceptionServiceLevelPolicy.code == code)) is None:
            session.add(ExceptionServiceLevelPolicy(tenant_id=tenant.id, code=code, name=name, severity=severity, response_hours=response, resolution_hours=resolution, escalation_hours=escalation, business_hours_only=False, configuration_json={}, is_active=True))
    for code in RESOLUTION_CODES:
        if session.scalar(select(ExceptionResolutionCode).where(ExceptionResolutionCode.tenant_id == tenant.id, ExceptionResolutionCode.code == code)) is None:
            session.add(ExceptionResolutionCode(tenant_id=tenant.id, code=code, name=code.replace("_", " ").title(), description=code.replace("_", " ").title(), is_active=True))
    session.commit()
    from app.services.ingestion_seed import seed_ingestion_data

    seed_ingestion_data(session)
    from app.services.canonical_seed import seed_canonical_data

    seed_canonical_data(session)
    from app.services.messy_seed import seed_messy_data

    seed_messy_data(session)
    from app.services.validation_seed import seed_validation_data

    seed_validation_data(session)
    from app.services.invoice_collections_seed import seed_invoice_collections_data
    from app.services.payroll_reconciliation_seed import seed_payroll_reconciliation_data
    from app.services.reconciliation_seed import seed_reconciliation_data

    seed_reconciliation_data(session, settings)
    seed_payroll_reconciliation_data(session, settings)
    seed_invoice_collections_data(session, settings)
    return {
        "tenants": 1,
        "users": len(users),
        "roles": len(roles),
        "permissions": len(permissions),
        "pipeline_definitions": 2,
    }
