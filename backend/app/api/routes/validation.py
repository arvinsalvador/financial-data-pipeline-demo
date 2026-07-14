from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    ValidationIssue,
    ValidationReport,
    ValidationRule,
    ValidationRuleSet,
    ValidationRun,
    ValidationRunResult,
    ValidationStatistic,
    ValidationSummary,
)
from app.schemas.generation import GeneratedPage
from app.schemas.validation import (
    RunValidationRequest,
    ValidationIssueResponse,
    ValidationReportResponse,
    ValidationResultResponse,
    ValidationRuleResponse,
    ValidationRunResponse,
    ValidationStatisticResponse,
    ValidationSummaryResponse,
)
from app.services.governance import AuditService
from app.services.validation_engine_service import ValidationEngine, ValidationEngineError

router = APIRouter(prefix="/validation")


def _owned(session: Session, tenant_id: int, run_id: int) -> ValidationRun:
    run = session.scalar(
        select(ValidationRun).where(
            ValidationRun.id == run_id, ValidationRun.tenant_id == tenant_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Validation run not found")
    return run


def _page(
    session: Session,
    model: Any,
    conditions: list[Any],
    page: int,
    page_size: int,
    schema: Any,
    order: Any,
) -> GeneratedPage:
    total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    items = session.scalars(
        select(model)
        .where(*conditions)
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return GeneratedPage(
        items=[schema.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/run", response_model=ValidationRunResponse)
def run_validation(
    body: RunValidationRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(require_permission("validation.execute"))],
) -> ValidationRunResponse:
    audit = AuditService()
    audit.record(
        session,
        context,
        event_type="validation.started",
        entity_type="validation_run",
        entity_id=None,
        action="execute",
        description="Validation started",
        metadata=body.model_dump(mode="json"),
    )
    session.commit()
    try:
        run, no_op = ValidationEngine(settings).run(
            session,
            context.tenant,
            body.target_type,
            body.target_id,
            body.rule_set_code,
            body.force_rerun,
        )
    except (ValidationEngineError, ValueError) as error:
        audit.record(
            session,
            context,
            event_type="validation.failed",
            entity_type="validation_run",
            entity_id=None,
            action="execute",
            description="Validation failed",
            metadata={"error": str(error)},
        )
        session.commit()
        raise HTTPException(status_code=422, detail=str(error)) from error
    audit.record(
        session,
        context,
        event_type="validation.completed",
        entity_type="validation_run",
        entity_id=run.id,
        action="execute",
        description="Validation completed",
        pipeline_run_id=run.pipeline_run_id,
        metadata={"issues": run.total_issues, "no_op": no_op},
    )
    for result in session.scalars(
        select(ValidationRunResult).where(
            ValidationRunResult.validation_run_id == run.id,
            ValidationRunResult.status.in_(("failed", "skipped", "disabled")),
        )
    ):
        audit.record(
            session,
            context,
            event_type=f"validation.rule_{result.status}",
            entity_type="validation_rule",
            entity_id=result.validation_rule_id,
            action=result.status,
            description=f"Validation rule {result.status}",
            pipeline_run_id=run.pipeline_run_id,
            metadata={"issues": result.issue_count},
        )
    if not no_op:
        audit.record(
            session,
            context,
            event_type="validation.report_generated",
            entity_type="validation_run",
            entity_id=run.id,
            action="report",
            description="Validation reports generated",
            pipeline_run_id=run.pipeline_run_id,
            metadata={"reports": 7},
        )
    session.commit()
    return ValidationRunResponse.model_validate(run).model_copy(update={"no_op": no_op})


@router.get("/runs", response_model=GeneratedPage)
def validation_runs(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.runs.view"))],
    pipeline: int | None = None,
    status: str | None = None,
    target_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    conditions: list[Any] = [ValidationRun.tenant_id == context.tenant.id]
    for value, field in (
        (pipeline, ValidationRun.pipeline_run_id),
        (status, ValidationRun.status),
        (target_type, ValidationRun.target_type),
    ):
        if value is not None:
            conditions.append(field == value)
    if date_from:
        conditions.append(ValidationRun.started_at >= date_from)
    if date_to:
        conditions.append(ValidationRun.started_at <= date_to)
    return _page(
        session,
        ValidationRun,
        conditions,
        page,
        page_size,
        ValidationRunResponse,
        ValidationRun.id.desc(),
    )


@router.get("/runs/{run_id}", response_model=ValidationRunResponse)
def validation_run(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.runs.view"))],
) -> ValidationRunResponse:
    return ValidationRunResponse.model_validate(_owned(session, context.tenant.id, run_id))


@router.get("/runs/{run_id}/results", response_model=GeneratedPage)
def validation_results(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.runs.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> GeneratedPage:
    _owned(session, context.tenant.id, run_id)
    return _page(
        session,
        ValidationRunResult,
        [ValidationRunResult.validation_run_id == run_id],
        page,
        page_size,
        ValidationResultResponse,
        ValidationRunResult.id,
    )


@router.get("/issues", response_model=GeneratedPage)
def validation_issues(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.issues.view"))],
    run_id: int | None = None,
    pipeline: int | None = None,
    file: str | None = None,
    source_file_id: int | None = None,
    severity: str | None = None,
    rule: str | None = None,
    entity: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GeneratedPage:
    conditions: list[Any] = [ValidationIssue.tenant_id == context.tenant.id]
    for value, field in (
        (run_id, ValidationIssue.validation_run_id),
        (file, ValidationIssue.filename),
        (source_file_id, ValidationIssue.source_file_id),
        (severity, ValidationIssue.severity),
        (entity, ValidationIssue.entity_type),
        (status, ValidationIssue.status),
    ):
        if value is not None:
            conditions.append(field == value)
    if pipeline is not None:
        run_ids = select(ValidationRun.id).where(
            ValidationRun.tenant_id == context.tenant.id,
            ValidationRun.pipeline_run_id == pipeline,
        )
        conditions.append(ValidationIssue.validation_run_id.in_(run_ids))
    if rule is not None:
        rule_ids = select(ValidationRule.id).where(ValidationRule.code == rule)
        conditions.append(ValidationIssue.validation_rule_id.in_(rule_ids))
    if date_from:
        conditions.append(ValidationIssue.detected_at >= date_from)
    if date_to:
        conditions.append(ValidationIssue.detected_at <= date_to)
    return _page(
        session,
        ValidationIssue,
        conditions,
        page,
        page_size,
        ValidationIssueResponse,
        ValidationIssue.id,
    )


@router.get("/issues/{issue_id}", response_model=ValidationIssueResponse)
def validation_issue(
    issue_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.issues.view"))],
) -> ValidationIssueResponse:
    issue = session.scalar(
        select(ValidationIssue).where(
            ValidationIssue.id == issue_id, ValidationIssue.tenant_id == context.tenant.id
        )
    )
    if issue is None:
        raise HTTPException(status_code=404, detail="Validation issue not found")
    return ValidationIssueResponse.model_validate(issue)


@router.get("/summary", response_model=ValidationSummaryResponse)
def validation_summary(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.statistics.view"))],
    run_id: int | None = None,
) -> ValidationSummaryResponse:
    target = run_id or session.scalar(
        select(ValidationRun.id)
        .where(ValidationRun.tenant_id == context.tenant.id)
        .order_by(ValidationRun.id.desc())
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Validation summary not found")
    _owned(session, context.tenant.id, target)
    summary = session.scalar(
        select(ValidationSummary).where(ValidationSummary.validation_run_id == target)
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Validation summary not found")
    return ValidationSummaryResponse.model_validate(summary)


@router.get("/statistics", response_model=GeneratedPage)
def validation_statistics(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.statistics.view"))],
    run_id: int | None = None,
    dimension: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 200,
) -> GeneratedPage:
    run_ids = select(ValidationRun.id).where(ValidationRun.tenant_id == context.tenant.id)
    conditions: list[Any] = [ValidationStatistic.validation_run_id.in_(run_ids)]
    if run_id is not None:
        _owned(session, context.tenant.id, run_id)
        conditions.append(ValidationStatistic.validation_run_id == run_id)
    if dimension:
        conditions.append(ValidationStatistic.dimension_type == dimension)
    return _page(
        session,
        ValidationStatistic,
        conditions,
        page,
        page_size,
        ValidationStatisticResponse,
        ValidationStatistic.id,
    )


@router.get("/reports", response_model=GeneratedPage)
def validation_reports(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.reports.view"))],
    run_id: int | None = None,
    report_type: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> GeneratedPage:
    run_ids = select(ValidationRun.id).where(ValidationRun.tenant_id == context.tenant.id)
    conditions: list[Any] = [ValidationReport.validation_run_id.in_(run_ids)]
    if run_id is not None:
        _owned(session, context.tenant.id, run_id)
        conditions.append(ValidationReport.validation_run_id == run_id)
    if report_type:
        conditions.append(ValidationReport.report_type == report_type)
    return _page(
        session,
        ValidationReport,
        conditions,
        page,
        page_size,
        ValidationReportResponse,
        ValidationReport.id,
    )


@router.get("/rules", response_model=list[ValidationRuleResponse])
def validation_rules(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("validation.rules.view"))],
    group: str | None = None,
    enabled: bool | None = None,
) -> list[ValidationRuleResponse]:
    rule_set_ids = select(ValidationRuleSet.id).where(
        ValidationRuleSet.tenant_id == context.tenant.id,
        ValidationRuleSet.is_active.is_(True),
    )
    conditions: list[Any] = [ValidationRule.validation_rule_set_id.in_(rule_set_ids)]
    if group:
        conditions.append(ValidationRule.rule_group == group)
    if enabled is not None:
        conditions.append(ValidationRule.is_enabled.is_(enabled))
    items = session.scalars(
        select(ValidationRule).where(*conditions).order_by(ValidationRule.execution_order)
    ).all()
    return [ValidationRuleResponse.model_validate(item) for item in items]
