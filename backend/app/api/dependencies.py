from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import Role, RolePermission, Tenant, TenantUser, TenantUserRole, User


@dataclass(frozen=True)
class RequestContext:
    tenant: Tenant
    actor: User
    permissions: frozenset[str]
    roles: frozenset[str]


def resolve_request_context(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    tenant_code: Annotated[str | None, Header(alias="X-Tenant-Code")] = None,
    actor_email: Annotated[str | None, Header(alias="X-Demo-User")] = None,
) -> RequestContext:
    if not settings.demo_actor_headers_enabled:
        raise HTTPException(status_code=401, detail="Development actor headers are disabled")
    if not tenant_code:
        raise HTTPException(status_code=400, detail="X-Tenant-Code is required")
    if not actor_email:
        raise HTTPException(status_code=401, detail="X-Demo-User is required")
    tenant = session.scalar(select(Tenant).where(Tenant.code == tenant_code.strip().lower()))
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=403, detail="Tenant context is not active")
    actor = session.scalar(select(User).where(User.email == actor_email.strip().lower()))
    if actor is None or actor.status != "active":
        raise HTTPException(status_code=401, detail="Development actor is not active")
    if actor.is_platform_admin:
        return RequestContext(tenant, actor, frozenset({"*"}), frozenset({"platform_admin"}))
    membership = session.scalar(
        select(TenantUser)
        .where(
            TenantUser.tenant_id == tenant.id,
            TenantUser.user_id == actor.id,
            TenantUser.status == "active",
        )
        .options(
            selectinload(TenantUser.role_assignments)
            .selectinload(TenantUserRole.role)
            .selectinload(Role.permissions)
            .selectinload(RolePermission.permission)
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Active tenant membership is required")
    roles = frozenset(assignment.role.code for assignment in membership.role_assignments)
    permissions = frozenset(
        role_permission.permission.code
        for assignment in membership.role_assignments
        for role_permission in assignment.role.permissions
    )
    return RequestContext(tenant, actor, permissions, roles)


def require_permission(permission: str) -> Callable[..., RequestContext]:
    def dependency(
        context: Annotated[RequestContext, Depends(resolve_request_context)],
    ) -> RequestContext:
        if "*" not in context.permissions and permission not in context.permissions:
            raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
        return context

    return dependency
