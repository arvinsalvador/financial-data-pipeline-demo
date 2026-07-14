from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from app.api.dependencies import RequestContext, require_permission, resolve_request_context
from app.db.session import get_db
from app.models import (
    AuditEvent,
    Permission,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    Role,
    RolePermission,
    Tenant,
    TenantUser,
    TenantUserRole,
    User,
)
from app.schemas.governance import (
    AuditEventResponse,
    MembershipCreate,
    MembershipResponse,
    MembershipUpdate,
    PermissionResponse,
    PipelineArtifactResponse,
    PipelineDefinitionResponse,
    RoleAssign,
    RoleResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.governance import MembershipService, TenantService, UserService

router = APIRouter()


def _conflict(error: ValueError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(error))


def _membership_response(membership: TenantUser) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        user_email=membership.user.email,
        user_display_name=membership.user.display_name,
        status=membership.status,
        roles=[assignment.role.code for assignment in membership.role_assignments],
        joined_at=membership.joined_at,
        created_at=membership.created_at,
    )


def _membership_query() -> Select[tuple[TenantUser]]:
    return select(TenantUser).options(
        selectinload(TenantUser.user),
        selectinload(TenantUser.role_assignments).selectinload(TenantUserRole.role),
    )


@router.get("/tenants", response_model=list[TenantResponse])
def list_tenants(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(resolve_request_context)],
) -> list[TenantResponse]:
    query = select(Tenant).order_by(Tenant.name)
    if not context.actor.is_platform_admin:
        query = query.where(Tenant.id == context.tenant.id)
    return [TenantResponse.model_validate(item) for item in session.scalars(query)]


@router.post("/tenants", response_model=TenantResponse, status_code=201)
def create_tenant(
    body: TenantCreate,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("tenants.manage"))],
) -> TenantResponse:
    try:
        tenant = TenantService().create(session, context, body.model_dump())
    except ValueError as error:
        raise _conflict(error) from error
    return TenantResponse.model_validate(tenant)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("tenants.view"))],
) -> TenantResponse:
    del context
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.model_validate(tenant)


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("tenants.manage"))],
) -> TenantResponse:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.model_validate(
        TenantService().update(session, context, tenant, body.model_dump(exclude_unset=True))
    )


@router.post("/tenants/{tenant_id}/archive", response_model=TenantResponse)
def archive_tenant(
    tenant_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("tenants.manage"))],
) -> TenantResponse:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.model_validate(
        TenantService().set_archived(session, context, tenant, True)
    )


@router.post("/tenants/{tenant_id}/restore", response_model=TenantResponse)
def restore_tenant(
    tenant_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("tenants.manage"))],
) -> TenantResponse:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.model_validate(
        TenantService().set_archived(session, context, tenant, False)
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("users.view"))],
) -> list[UserResponse]:
    query = select(User).order_by(User.email)
    if not context.actor.is_platform_admin:
        query = query.join(TenantUser).where(TenantUser.tenant_id == context.tenant.id)
    return [UserResponse.model_validate(item) for item in session.scalars(query)]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    body: UserCreate,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("users.manage"))],
) -> UserResponse:
    try:
        user = UserService().create(session, context, body.model_dump())
    except ValueError as error:
        raise _conflict(error) from error
    return UserResponse.model_validate(user)


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("users.view"))],
) -> UserResponse:
    query = select(User).where(User.id == user_id)
    if not context.actor.is_platform_admin:
        query = query.join(TenantUser).where(TenantUser.tenant_id == context.tenant.id)
    user = session.scalar(query)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    body: UserUpdate,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("users.manage"))],
) -> UserResponse:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(
        UserService().update(session, context, user, body.model_dump(exclude_unset=True))
    )


@router.get("/tenants/{tenant_id}/members", response_model=list[MembershipResponse])
def list_members(
    tenant_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("users.view"))],
) -> list[MembershipResponse]:
    if not context.actor.is_platform_admin and tenant_id != context.tenant.id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    items = session.scalars(
        _membership_query().where(TenantUser.tenant_id == tenant_id).order_by(TenantUser.id)
    ).all()
    return [_membership_response(item) for item in items]


@router.post("/tenants/{tenant_id}/members", response_model=MembershipResponse, status_code=201)
def create_membership(
    tenant_id: int,
    body: MembershipCreate,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("users.manage"))],
) -> MembershipResponse:
    tenant, user = session.get(Tenant, tenant_id), session.get(User, body.user_id)
    if tenant is None or user is None:
        raise HTTPException(status_code=404, detail="Tenant or user not found")
    try:
        MembershipService().create(session, context, tenant, user, body.status)
    except ValueError as error:
        raise _conflict(error) from error
    membership = session.scalar(
        _membership_query().where(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user.id)
    )
    if membership is None:
        raise RuntimeError("Created membership could not be loaded")
    return _membership_response(membership)


@router.patch("/tenant-memberships/{membership_id}", response_model=MembershipResponse)
def update_membership(
    membership_id: int,
    body: MembershipUpdate,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("users.manage"))],
) -> MembershipResponse:
    membership = session.scalar(_membership_query().where(TenantUser.id == membership_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    MembershipService().set_status(session, context, membership, body.status)
    loaded = session.scalar(_membership_query().where(TenantUser.id == membership_id))
    if loaded is None:
        raise RuntimeError("Updated membership could not be loaded")
    return _membership_response(loaded)


@router.post("/tenant-memberships/{membership_id}/roles", status_code=204)
def assign_role(
    membership_id: int,
    body: RoleAssign,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("roles.manage"))],
) -> Response:
    membership, role = session.get(TenantUser, membership_id), session.get(Role, body.role_id)
    if membership is None or role is None:
        raise HTTPException(status_code=404, detail="Membership or role not found")
    try:
        MembershipService().assign_role(session, context, membership, role)
    except ValueError as error:
        raise _conflict(error) from error
    return Response(status_code=204)


@router.delete("/tenant-memberships/{membership_id}/roles/{role_id}", status_code=204)
def remove_role(
    membership_id: int,
    role_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("roles.manage"))],
) -> Response:
    assignment = session.scalar(
        select(TenantUserRole)
        .where(TenantUserRole.tenant_user_id == membership_id, TenantUserRole.role_id == role_id)
        .options(selectinload(TenantUserRole.role))
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Role assignment not found")
    MembershipService().remove_role(session, context, assignment)
    return Response(status_code=204)


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("roles.view"))],
) -> list[RoleResponse]:
    del context
    return [
        RoleResponse.model_validate(item)
        for item in session.scalars(select(Role).order_by(Role.code))
    ]


@router.get("/permissions", response_model=list[PermissionResponse])
def list_permissions(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("roles.view"))],
) -> list[PermissionResponse]:
    del context
    return [
        PermissionResponse.model_validate(item)
        for item in session.scalars(select(Permission).order_by(Permission.code))
    ]


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionResponse])
def role_permissions(
    role_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("roles.view"))],
) -> list[PermissionResponse]:
    del context
    items = session.scalars(
        select(Permission)
        .join(RolePermission)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.code)
    ).all()
    return [PermissionResponse.model_validate(item) for item in items]


@router.get("/audit-events")
def list_audit_events(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("audit_events.view"))],
    tenant_id: int | None = None,
    actor_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    event_type: str | None = None,
    pipeline_run_id: int | None = None,
    source_file_id: int | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    effective_tenant = (
        tenant_id
        if context.actor.is_platform_admin and tenant_id is not None
        else context.tenant.id
    )
    conditions = [AuditEvent.tenant_id == effective_tenant]
    for column, value in (
        (AuditEvent.actor_user_id, actor_user_id),
        (AuditEvent.entity_type, entity_type),
        (AuditEvent.entity_id, entity_id),
        (AuditEvent.action, action),
        (AuditEvent.event_type, event_type),
        (AuditEvent.pipeline_run_id, pipeline_run_id),
        (AuditEvent.source_file_id, source_file_id),
    ):
        if value is not None:
            conditions.append(column == value)
    if occurred_from is not None:
        conditions.append(AuditEvent.occurred_at >= occurred_from)
    if occurred_to is not None:
        conditions.append(AuditEvent.occurred_at <= occurred_to)
    total = session.scalar(select(func.count()).select_from(AuditEvent).where(*conditions)) or 0
    items = session.scalars(
        select(AuditEvent)
        .where(*conditions)
        .options(selectinload(AuditEvent.changes))
        .order_by(AuditEvent.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            AuditEventResponse.model_validate(item).model_dump(mode="json") for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/audit-events/{audit_event_id}", response_model=AuditEventResponse)
def get_audit_event(
    audit_event_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("audit_events.view"))],
) -> AuditEventResponse:
    query = select(AuditEvent).where(AuditEvent.id == audit_event_id)
    if not context.actor.is_platform_admin:
        query = query.where(AuditEvent.tenant_id == context.tenant.id)
    event = session.scalar(query.options(selectinload(AuditEvent.changes)))
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return AuditEventResponse.model_validate(event)


@router.get("/pipeline-definitions", response_model=list[PipelineDefinitionResponse])
def list_pipeline_definitions(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("pipeline_runs.view"))],
) -> list[PipelineDefinitionResponse]:
    del context
    return [
        PipelineDefinitionResponse.model_validate(item)
        for item in session.scalars(select(PipelineDefinition).order_by(PipelineDefinition.code))
    ]


@router.get("/pipeline-definitions/{definition_id}", response_model=PipelineDefinitionResponse)
def get_pipeline_definition(
    definition_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("pipeline_runs.view"))],
) -> PipelineDefinitionResponse:
    del context
    item = session.get(PipelineDefinition, definition_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pipeline definition not found")
    return PipelineDefinitionResponse.model_validate(item)


@router.get(
    "/pipeline-runs/{pipeline_run_id}/artifacts", response_model=list[PipelineArtifactResponse]
)
def list_pipeline_artifacts(
    pipeline_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("pipeline_runs.view"))],
) -> list[PipelineArtifactResponse]:
    run = session.scalar(
        select(PipelineRun).where(
            PipelineRun.id == pipeline_run_id, PipelineRun.tenant_id == context.tenant.id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    items = session.scalars(
        select(PipelineRunArtifact).where(
            PipelineRunArtifact.pipeline_run_id == run.id,
            PipelineRunArtifact.tenant_id == context.tenant.id,
        )
    ).all()
    return [PipelineArtifactResponse.model_validate(item) for item in items]


@router.get("/pipeline-artifacts/{artifact_id}", response_model=PipelineArtifactResponse)
def get_pipeline_artifact(
    artifact_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("pipeline_runs.view"))],
) -> PipelineArtifactResponse:
    artifact = session.scalar(
        select(PipelineRunArtifact).where(
            PipelineRunArtifact.id == artifact_id,
            PipelineRunArtifact.tenant_id == context.tenant.id,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Pipeline artifact not found")
    return PipelineArtifactResponse.model_validate(artifact)
