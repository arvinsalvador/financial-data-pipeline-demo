from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext
from app.models import (
    AuditEvent,
    AuditEventChange,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    Role,
    Tenant,
    TenantUser,
    TenantUserRole,
    User,
)

TENANT_STATUSES = {"active", "inactive", "suspended", "archived"}
USER_STATUSES = {"invited", "active", "inactive", "suspended", "archived"}
MEMBERSHIP_STATUSES = {"invited", "active", "suspended", "removed"}
SENSITIVE_FIELDS = {"password", "password_hash", "token", "access_token", "secret"}


def normalize_email(value: str) -> str:
    return value.strip().lower()


def safe_audit_value(field_name: str, value: Any) -> Any:
    if any(secret in field_name.lower() for secret in SENSITIVE_FIELDS):
        return "[REDACTED]"
    rendered = str(value)
    return rendered[:500] + ("…" if len(rendered) > 500 else "") if len(rendered) > 500 else value


class AuditService:
    def record(
        self,
        session: Session,
        context: RequestContext,
        *,
        event_type: str,
        entity_type: str,
        entity_id: int | str | None,
        action: str,
        description: str,
        pipeline_run_id: int | None = None,
        source_file_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        changes: dict[str, tuple[Any, Any]] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            tenant_id=context.tenant.id,
            actor_user_id=context.actor.id,
            actor_type="user",
            event_type=event_type,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            action=action,
            description=description,
            pipeline_run_id=pipeline_run_id,
            source_file_id=source_file_id,
            metadata_json={
                key: safe_audit_value(key, value) for key, value in (metadata or {}).items()
            },
            occurred_at=datetime.now(UTC),
        )
        for field_name, (old, new) in (changes or {}).items():
            event.changes.append(
                AuditEventChange(
                    field_name=field_name,
                    old_value_json=safe_audit_value(field_name, old),
                    new_value_json=safe_audit_value(field_name, new),
                )
            )
        session.add(event)
        session.flush()
        return event


class TenantService:
    def create(self, session: Session, context: RequestContext, values: dict[str, Any]) -> Tenant:
        code = str(values["code"]).strip().lower()
        if session.scalar(select(Tenant).where(Tenant.code == code)) is not None:
            raise ValueError("Tenant code already exists")
        tenant = Tenant(code=code, **{key: value for key, value in values.items() if key != "code"})
        session.add(tenant)
        session.flush()
        AuditService().record(
            session,
            context,
            event_type="tenant.created",
            entity_type="tenant",
            entity_id=tenant.id,
            action="create",
            description=f"Created tenant {tenant.code}",
        )
        session.commit()
        session.refresh(tenant)
        return tenant

    def update(
        self, session: Session, context: RequestContext, tenant: Tenant, values: dict[str, Any]
    ) -> Tenant:
        changes = {}
        for field, value in values.items():
            old = getattr(tenant, field)
            if old != value:
                changes[field] = (old, value)
                setattr(tenant, field, value)
        AuditService().record(
            session,
            context,
            event_type="tenant.updated",
            entity_type="tenant",
            entity_id=tenant.id,
            action="update",
            description=f"Updated tenant {tenant.code}",
            changes=changes,
        )
        session.commit()
        session.refresh(tenant)
        return tenant

    def set_archived(
        self, session: Session, context: RequestContext, tenant: Tenant, archived: bool
    ) -> Tenant:
        old_status = tenant.status
        tenant.status = "archived" if archived else "active"
        tenant.archived_at = datetime.now(UTC) if archived else None
        AuditService().record(
            session,
            context,
            event_type="tenant.archived" if archived else "tenant.restored",
            entity_type="tenant",
            entity_id=tenant.id,
            action="archive" if archived else "restore",
            description=f"{'Archived' if archived else 'Restored'} tenant {tenant.code}",
            changes={"status": (old_status, tenant.status)},
        )
        session.commit()
        session.refresh(tenant)
        return tenant


class UserService:
    def create(self, session: Session, context: RequestContext, values: dict[str, Any]) -> User:
        email = normalize_email(str(values["email"]))
        if session.scalar(select(User).where(User.email == email)) is not None:
            raise ValueError("User email already exists")
        user = User(
            email=email,
            password_hash=None,
            **{key: value for key, value in values.items() if key != "email"},
        )
        session.add(user)
        session.flush()
        AuditService().record(
            session,
            context,
            event_type="user.created",
            entity_type="user",
            entity_id=user.id,
            action="create",
            description=f"Created user {email}",
        )
        session.commit()
        session.refresh(user)
        return user

    def update(
        self, session: Session, context: RequestContext, user: User, values: dict[str, Any]
    ) -> User:
        changes = {}
        for field, value in values.items():
            old = getattr(user, field)
            if old != value:
                changes[field] = (old, value)
                setattr(user, field, value)
        AuditService().record(
            session,
            context,
            event_type="user.updated",
            entity_type="user",
            entity_id=user.id,
            action="update",
            description=f"Updated user {user.email}",
            changes=changes,
        )
        session.commit()
        session.refresh(user)
        return user


class MembershipService:
    def create(
        self, session: Session, context: RequestContext, tenant: Tenant, user: User, status: str
    ) -> TenantUser:
        if (
            session.scalar(
                select(TenantUser).where(
                    TenantUser.tenant_id == tenant.id, TenantUser.user_id == user.id
                )
            )
            is not None
        ):
            raise ValueError("Membership already exists")
        membership = TenantUser(
            tenant_id=tenant.id,
            user_id=user.id,
            status=status,
            joined_at=datetime.now(UTC) if status == "active" else None,
        )
        session.add(membership)
        session.flush()
        AuditService().record(
            session,
            context,
            event_type="membership.created",
            entity_type="tenant_user",
            entity_id=membership.id,
            action="create",
            description=f"Added {user.email} to {tenant.code}",
        )
        session.commit()
        session.refresh(membership)
        return membership

    def set_status(
        self, session: Session, context: RequestContext, membership: TenantUser, status: str
    ) -> TenantUser:
        old = membership.status
        membership.status = status
        membership.suspended_at = datetime.now(UTC) if status == "suspended" else None
        AuditService().record(
            session,
            context,
            event_type="membership.updated",
            entity_type="tenant_user",
            entity_id=membership.id,
            action="update",
            description="Changed tenant membership status",
            changes={"status": (old, status)},
        )
        session.commit()
        session.refresh(membership)
        return membership

    def assign_role(
        self, session: Session, context: RequestContext, membership: TenantUser, role: Role
    ) -> TenantUserRole:
        if role.scope != "tenant":
            raise ValueError("Only tenant-scoped roles may be assigned")
        if (
            session.scalar(
                select(TenantUserRole).where(
                    TenantUserRole.tenant_user_id == membership.id,
                    TenantUserRole.role_id == role.id,
                )
            )
            is not None
        ):
            raise ValueError("Role is already assigned")
        assignment = TenantUserRole(
            tenant_user_id=membership.id,
            role_id=role.id,
            assigned_by_user_id=context.actor.id,
            assigned_at=datetime.now(UTC),
        )
        session.add(assignment)
        session.flush()
        AuditService().record(
            session,
            context,
            event_type="membership.role_assigned",
            entity_type="tenant_user",
            entity_id=membership.id,
            action="assign_role",
            description=f"Assigned role {role.code}",
            metadata={"role_code": role.code},
        )
        session.commit()
        return assignment

    def remove_role(
        self, session: Session, context: RequestContext, assignment: TenantUserRole
    ) -> None:
        role_code = assignment.role.code
        membership_id = assignment.tenant_user_id
        session.delete(assignment)
        AuditService().record(
            session,
            context,
            event_type="membership.role_removed",
            entity_type="tenant_user",
            entity_id=membership_id,
            action="remove_role",
            description=f"Removed role {role_code}",
            metadata={"role_code": role_code},
        )
        session.commit()


class PipelineDefinitionService:
    def active_for(self, session: Session, code: str) -> PipelineDefinition:
        definition = session.scalar(
            select(PipelineDefinition)
            .where(PipelineDefinition.code == code, PipelineDefinition.is_active.is_(True))
            .order_by(PipelineDefinition.id.desc())
        )
        if definition is None:
            raise RuntimeError(f"Pipeline definition {code} is not active")
        return definition


class PipelineArtifactService:
    def register(
        self,
        session: Session,
        context: RequestContext,
        pipeline_run: PipelineRun,
        values: dict[str, Any],
    ) -> PipelineRunArtifact:
        relative_path = Path(str(values["relative_path"]))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Artifact path must be a safe relative path")
        if pipeline_run.tenant_id != context.tenant.id:
            raise ValueError("Pipeline run belongs to another tenant")
        artifact = PipelineRunArtifact(
            tenant_id=context.tenant.id, pipeline_run_id=pipeline_run.id, **values
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return artifact
