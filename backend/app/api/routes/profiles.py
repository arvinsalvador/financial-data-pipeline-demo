from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement, Select

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import DataQualityIssue, SourceFileColumnProfile, SourceFileProfile
from app.schemas.profiles import (
    ColumnProfilePage,
    ColumnProfileResponse,
    IssuePage,
    IssueResponse,
    ProfilePage,
    ProfileResponse,
)
from app.services.csv_profiling import ProfilingError, ProfilingOrchestrationService
from app.services.governance import AuditService

router = APIRouter()


def profile_response(session: Session, profile: SourceFileProfile) -> ProfileResponse:
    severity_rows = session.execute(
        select(DataQualityIssue.severity, func.count())
        .where(DataQualityIssue.source_file_profile_id == profile.id)
        .group_by(DataQualityIssue.severity)
    ).all()
    response = ProfileResponse.model_validate(profile)
    response.issue_totals = {severity: count for severity, count in severity_rows}
    return response


@router.post("/source-files/{source_file_id}/profile", response_model=ProfileResponse)
def profile_source_file(
    source_file_id: int,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(require_permission("source_files.profile"))],
) -> ProfileResponse:
    try:
        profile = ProfilingOrchestrationService(settings).profile(
            session, source_file_id, context.tenant.id
        )
    except ProfilingError as error:
        AuditService().record(
            session,
            context,
            event_type="source_file.profiling_failed",
            entity_type="source_file",
            entity_id=source_file_id,
            action="profile",
            description="CSV profiling failed",
            metadata={"error": str(error)},
        )
        session.commit()
        raise HTTPException(
            status_code=404 if str(error) == "Source file not found" else 422, detail=str(error)
        ) from error
    AuditService().record(
        session,
        context,
        event_type="source_file.profiled",
        entity_type="source_file_profile",
        entity_id=profile.id,
        action="profile",
        description="Profiled registered CSV source",
        pipeline_run_id=profile.pipeline_run_id,
        source_file_id=source_file_id,
        metadata={"status": profile.status, "profile_version": profile.profile_version},
    )
    session.commit()
    return profile_response(session, profile)


@router.get("/source-files/{source_file_id}/profiles", response_model=ProfilePage)
def list_source_profiles(
    source_file_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("profiles.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProfilePage:
    condition = (SourceFileProfile.source_file_id == source_file_id) & (
        SourceFileProfile.tenant_id == context.tenant.id
    )
    total = (
        session.scalar(select(func.count()).select_from(SourceFileProfile).where(condition)) or 0
    )
    profiles = session.scalars(
        select(SourceFileProfile)
        .where(condition)
        .order_by(SourceFileProfile.generated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ProfilePage(
        items=[profile_response(session, item) for item in profiles],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/source-files/{source_file_id}/profiles/latest", response_model=ProfileResponse)
def latest_source_profile(
    source_file_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("profiles.view"))],
) -> ProfileResponse:
    profile = session.scalar(
        select(SourceFileProfile)
        .where(
            SourceFileProfile.source_file_id == source_file_id,
            SourceFileProfile.tenant_id == context.tenant.id,
        )
        .order_by(SourceFileProfile.generated_at.desc())
        .limit(1)
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile_response(session, profile)


@router.get("/profiles/{profile_id}", response_model=ProfileResponse)
def get_profile(
    profile_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("profiles.view"))],
) -> ProfileResponse:
    profile = session.scalar(
        select(SourceFileProfile).where(
            SourceFileProfile.id == profile_id, SourceFileProfile.tenant_id == context.tenant.id
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile_response(session, profile)


@router.get("/profiles/{profile_id}/columns", response_model=ColumnProfilePage)
def list_profile_columns(
    profile_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("profiles.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ColumnProfilePage:
    owned = session.scalar(
        select(SourceFileProfile.id).where(
            SourceFileProfile.id == profile_id, SourceFileProfile.tenant_id == context.tenant.id
        )
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    condition = SourceFileColumnProfile.source_file_profile_id == profile_id
    total = (
        session.scalar(select(func.count()).select_from(SourceFileColumnProfile).where(condition))
        or 0
    )
    items = session.scalars(
        select(SourceFileColumnProfile)
        .where(condition)
        .order_by(SourceFileColumnProfile.column_position)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ColumnProfilePage(
        items=[ColumnProfileResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def _issue_query(
    tenant_id: int,
    source_file_id: int | None,
    profile_id: int | None,
    severity: str | None,
    issue_type: str | None,
    issue_code: str | None,
    status: str | None,
    column_name: str | None,
) -> tuple[Select[tuple[DataQualityIssue]], list[ColumnElement[bool]]]:
    conditions: list[ColumnElement[bool]] = [DataQualityIssue.tenant_id == tenant_id]
    for column, value in (
        (DataQualityIssue.source_file_id, source_file_id),
        (DataQualityIssue.source_file_profile_id, profile_id),
        (DataQualityIssue.severity, severity),
        (DataQualityIssue.issue_type, issue_type),
        (DataQualityIssue.issue_code, issue_code),
        (DataQualityIssue.status, status),
        (DataQualityIssue.column_name, column_name),
    ):
        if value is not None:
            conditions.append(column == value)
    return select(DataQualityIssue).where(*conditions), conditions


def issue_page(
    session: Session,
    query: Select[tuple[DataQualityIssue]],
    conditions: list[ColumnElement[bool]],
    page: int,
    page_size: int,
) -> IssuePage:
    total = (
        session.scalar(select(func.count()).select_from(DataQualityIssue).where(*conditions)) or 0
    )
    items = session.scalars(
        query.order_by(DataQualityIssue.detected_at.desc(), DataQualityIssue.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return IssuePage(
        items=[IssueResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/profiles/{profile_id}/issues", response_model=IssuePage)
def list_profile_issues(
    profile_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("data_quality_issues.view"))],
    severity: str | None = None,
    issue_type: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> IssuePage:
    owned = session.scalar(
        select(SourceFileProfile.id).where(
            SourceFileProfile.id == profile_id,
            SourceFileProfile.tenant_id == context.tenant.id,
        )
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    query, conditions = _issue_query(
        context.tenant.id, None, profile_id, severity, issue_type, None, None, None
    )
    return issue_page(session, query, conditions, page, page_size)


@router.get("/data-quality-issues", response_model=IssuePage)
def list_issues(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("data_quality_issues.view"))],
    source_file_id: int | None = None,
    profile_id: int | None = None,
    severity: str | None = None,
    issue_type: str | None = None,
    issue_code: str | None = None,
    status: str | None = None,
    column_name: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> IssuePage:
    query, conditions = _issue_query(
        context.tenant.id,
        source_file_id,
        profile_id,
        severity,
        issue_type,
        issue_code,
        status,
        column_name,
    )
    return issue_page(session, query, conditions, page, page_size)


@router.get("/data-quality-issues/{issue_id}", response_model=IssueResponse)
def get_issue(
    issue_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("data_quality_issues.view"))],
) -> IssueResponse:
    issue = session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.id == issue_id, DataQualityIssue.tenant_id == context.tenant.id
        )
    )
    if issue is None:
        raise HTTPException(status_code=404, detail="Data-quality issue not found")
    return IssueResponse.model_validate(issue)
