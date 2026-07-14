from sqlalchemy import func, select, text

from app.db.session import SessionLocal
from app.models import (
    AuditEvent,
    DataQualityIssue,
    PipelineRun,
    SourceFile,
    SourceFileProfile,
    SourceSystem,
    Tenant,
    TenantUser,
    TenantUserRole,
)


def main() -> None:
    errors: list[str] = []
    with SessionLocal() as session:
        for model in (SourceSystem, SourceFile, SourceFileProfile, DataQualityIssue, PipelineRun):
            missing = (
                session.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id.is_(None))
                )
                or 0
            )
            print(f"{model.__tablename__}: missing_tenant_id={missing}")
            if missing:
                errors.append(f"{model.__tablename__} has missing tenant ownership")
        inactive = (
            session.scalar(
                select(func.count())
                .select_from(SourceFile)
                .join(Tenant, Tenant.id == SourceFile.tenant_id)
                .where(Tenant.status != "active")
            )
            or 0
        )
        duplicate_codes = session.execute(
            text(
                "SELECT tenant_id,code,count(*) FROM source_systems "
                "GROUP BY tenant_id,code HAVING count(*)>1"
            )
        ).all()
        duplicate_checksums = session.execute(
            text(
                "SELECT tenant_id,sha256_checksum,count(*) FROM source_files "
                "GROUP BY tenant_id,sha256_checksum HAVING count(*)>1"
            )
        ).all()
        invalid_memberships = (
            session.scalar(
                select(func.count())
                .select_from(TenantUser)
                .where(~TenantUser.status.in_(["invited", "active", "suspended", "removed"]))
            )
            or 0
        )
        invalid_roles = (
            session.scalar(
                select(func.count())
                .select_from(TenantUserRole)
                .join(TenantUserRole.role)
                .where(text("roles.scope <> 'tenant'"))
            )
            or 0
        )
        missing_audit_tenant = (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id.is_(None), AuditEvent.entity_type != "platform")
            )
            or 0
        )
        checks = {
            "records_on_inactive_tenants": inactive,
            "duplicate_source_system_codes": len(duplicate_codes),
            "duplicate_source_checksums": len(duplicate_checksums),
            "invalid_memberships": invalid_memberships,
            "invalid_tenant_role_assignments": invalid_roles,
            "audit_events_missing_tenant": missing_audit_tenant,
        }
        for name, count in checks.items():
            print(f"{name}={count}")
            if count:
                errors.append(name)
    if errors:
        raise SystemExit("Critical governance integrity errors: " + ", ".join(errors))
    print("Tenant governance integrity verified successfully")


if __name__ == "__main__":
    main()
