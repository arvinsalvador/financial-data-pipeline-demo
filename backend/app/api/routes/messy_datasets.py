from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    DataMutation,
    DefectScenario,
    DefectScenarioRule,
    ExpectedException,
    MessyDatasetRun,
    MessyGenerationControlTotal,
    MessySourceFile,
    PipelineRunArtifact,
    PipelineRunStep,
)
from app.schemas.generation import GeneratedPage
from app.schemas.messy import (
    ExpectedExceptionResponse,
    GenerateMessyDatasetRequest,
    MessyControlResponse,
    MessyDatasetResponse,
    MessySourceFileResponse,
    MutationResponse,
    ScenarioResponse,
    ScenarioRuleResponse,
)
from app.services.governance import AuditService
from app.services.messy_generation import MessyDatasetService, MessyGenerationError

router = APIRouter()


def _run(
    run: MessyDatasetRun,
    no_op: bool = False,
    session: Session | None = None,
) -> MessyDatasetResponse:
    update: dict[str, Any] = {"no_op": no_op}
    if session is not None:
        steps = session.scalars(
            select(PipelineRunStep)
            .where(PipelineRunStep.pipeline_run_id == run.pipeline_run_id)
            .order_by(PipelineRunStep.step_order)
        ).all()
        artifacts = session.scalars(
            select(PipelineRunArtifact)
            .where(PipelineRunArtifact.pipeline_run_id == run.pipeline_run_id)
            .order_by(PipelineRunArtifact.id)
        ).all()
        update["pipeline_steps"] = [
            {column.name: getattr(item, column.name) for column in item.__table__.columns}
            for item in steps
        ]
        update["artifacts"] = [
            {column.name: getattr(item, column.name) for column in item.__table__.columns}
            for item in artifacts
        ]
    return MessyDatasetResponse.model_validate(run).model_copy(update=update)


def _owned(session: Session, tenant_id: int, run_id: int) -> MessyDatasetRun:
    run = session.scalar(
        select(MessyDatasetRun).where(
            MessyDatasetRun.id == run_id, MessyDatasetRun.tenant_id == tenant_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Messy dataset not found")
    return run


def _page(
    session: Session, model: Any, conditions: list[Any], page: int, page_size: int, schema: Any
) -> GeneratedPage:
    total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    items = session.scalars(
        select(model)
        .where(*conditions)
        .order_by(model.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return GeneratedPage(
        items=[schema.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/messy-datasets", response_model=MessyDatasetResponse)
def generate_messy_dataset(
    body: GenerateMessyDatasetRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(require_permission("messy_datasets.execute"))],
) -> MessyDatasetResponse:
    audit = AuditService()
    audit.record(
        session,
        context,
        event_type="messy_generation.requested",
        entity_type="messy_dataset",
        entity_id=None,
        action="generate",
        description="Controlled messy generation requested",
        metadata=body.model_dump(mode="json"),
    )
    audit.record(
        session,
        context,
        event_type="messy_generation.scenario_selected",
        entity_type="defect_scenario",
        entity_id=body.scenario_code,
        action="select",
        description="Defect scenario selected",
        metadata={"scenario_code": body.scenario_code},
    )
    session.commit()
    try:
        result = MessyDatasetService(settings).generate(
            session,
            context.tenant,
            body.clean_generated_dataset_run_id,
            body.scenario_code,
            body.random_seed,
            body.force_rerun,
        )
    except MessyGenerationError as error:
        audit.record(
            session,
            context,
            event_type="messy_generation.failed",
            entity_type="messy_dataset",
            entity_id=None,
            action="generate",
            description="Controlled messy generation failed",
            metadata={"error": str(error)},
        )
        session.commit()
        raise HTTPException(status_code=422, detail=str(error)) from error
    event = (
        "messy_generation.no_op"
        if result.no_op
        else (
            "messy_generation.completed_with_warnings"
            if result.run.status == "completed_with_warnings"
            else "messy_generation.completed"
        )
    )
    audit.record(
        session,
        context,
        event_type=event,
        entity_type="messy_dataset",
        entity_id=result.run.id,
        action="generate",
        description="Controlled messy generation handled",
        pipeline_run_id=result.run.pipeline_run_id,
        metadata={
            "applied": result.run.applied_defect_count,
            "skipped": result.run.skipped_defect_count,
            "expected": result.run.expected_exception_count,
        },
    )
    if body.force_rerun:
        audit.record(
            session,
            context,
            event_type="messy_generation.forced_rerun",
            entity_type="messy_dataset",
            entity_id=result.run.id,
            action="verify",
            description="Forced messy rerun verified",
            pipeline_run_id=result.run.pipeline_run_id,
            metadata={"no_op": result.no_op},
        )
    if not result.no_op:
        for mutation in session.scalars(
            select(DataMutation).where(DataMutation.messy_dataset_run_id == result.run.id)
        ):
            audit.record(
                session,
                context,
                event_type=f"messy_generation.mutation_{mutation.mutation_status}",
                entity_type="data_mutation",
                entity_id=mutation.id,
                action=mutation.mutation_status,
                description=f"Controlled mutation {mutation.mutation_status}",
                pipeline_run_id=result.run.pipeline_run_id,
                metadata={
                    "defect_type": mutation.defect_type,
                    "filename": mutation.target_filename,
                    "row": mutation.source_row_number,
                    "column": mutation.target_column,
                },
            )
        for file in session.scalars(
            select(MessySourceFile).where(MessySourceFile.messy_dataset_run_id == result.run.id)
        ):
            audit.record(
                session,
                context,
                event_type="messy_generation.file_registered",
                entity_type="messy_source_file",
                entity_id=file.id,
                action="register",
                description="Messy source file registered",
                pipeline_run_id=result.run.pipeline_run_id,
                source_file_id=file.source_file_id,
                metadata={"file_type": file.file_type, "checksum": file.sha256_checksum},
            )
    session.commit()
    return _run(result.run, result.no_op, session)


@router.get("/messy-datasets", response_model=GeneratedPage)
def messy_datasets(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("messy_datasets.view"))],
    status: str | None = None,
    scenario_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
) -> GeneratedPage:
    conditions: list[Any] = [MessyDatasetRun.tenant_id == context.tenant.id]
    if status:
        conditions.append(MessyDatasetRun.status == status)
    if scenario_id:
        conditions.append(MessyDatasetRun.defect_scenario_id == scenario_id)
    total = (
        session.scalar(select(func.count()).select_from(MessyDatasetRun).where(*conditions)) or 0
    )
    items = session.scalars(
        select(MessyDatasetRun)
        .where(*conditions)
        .order_by(MessyDatasetRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return GeneratedPage(
        items=[_run(item) for item in items], total=total, page=page, page_size=page_size
    )


@router.get("/messy-datasets/{run_id}", response_model=MessyDatasetResponse)
def messy_dataset(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("messy_datasets.view"))],
) -> MessyDatasetResponse:
    return _run(_owned(session, context.tenant.id, run_id), session=session)


@router.get("/messy-datasets/{run_id}/files", response_model=GeneratedPage)
def messy_files(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("messy_datasets.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned(session, context.tenant.id, run_id)
    return _page(
        session,
        MessySourceFile,
        [
            MessySourceFile.tenant_id == context.tenant.id,
            MessySourceFile.messy_dataset_run_id == run_id,
        ],
        page,
        page_size,
        MessySourceFileResponse,
    )


@router.get("/messy-datasets/{run_id}/mutations", response_model=GeneratedPage)
def mutations(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("data_mutations.view"))],
    defect_type: str | None = None,
    filename: str | None = None,
    row_number: int | None = None,
    column: str | None = None,
    mutation_status: str | None = None,
    scenario_rule_id: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned(session, context.tenant.id, run_id)
    conditions: list[Any] = [
        DataMutation.tenant_id == context.tenant.id,
        DataMutation.messy_dataset_run_id == run_id,
    ]
    for value, field in (
        (defect_type, DataMutation.defect_type),
        (filename, DataMutation.target_filename),
        (row_number, DataMutation.source_row_number),
        (column, DataMutation.target_column),
        (mutation_status, DataMutation.mutation_status),
        (scenario_rule_id, DataMutation.defect_scenario_rule_id),
    ):
        if value is not None:
            conditions.append(field == value)
    return _page(session, DataMutation, conditions, page, page_size, MutationResponse)


@router.get("/data-mutations/{mutation_id}", response_model=MutationResponse)
def mutation(
    mutation_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("data_mutations.view"))],
) -> MutationResponse:
    item = session.scalar(
        select(DataMutation).where(
            DataMutation.id == mutation_id, DataMutation.tenant_id == context.tenant.id
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Mutation not found")
    return MutationResponse.model_validate(item)


@router.get("/messy-datasets/{run_id}/expected-exceptions", response_model=GeneratedPage)
def expected_exceptions(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("expected_exceptions.view"))],
    exception_code: str | None = None,
    issue_type: str | None = None,
    severity: str | None = None,
    filename: str | None = None,
    row_number: int | None = None,
    column: str | None = None,
    status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned(session, context.tenant.id, run_id)
    conditions: list[Any] = [
        ExpectedException.tenant_id == context.tenant.id,
        ExpectedException.messy_dataset_run_id == run_id,
    ]
    for value, field in (
        (exception_code, ExpectedException.expected_exception_code),
        (issue_type, ExpectedException.expected_issue_type),
        (severity, ExpectedException.expected_severity),
        (filename, ExpectedException.expected_filename),
        (row_number, ExpectedException.expected_source_row_number),
        (column, ExpectedException.expected_column_name),
        (status, ExpectedException.status),
    ):
        if value is not None:
            conditions.append(field == value)
    return _page(session, ExpectedException, conditions, page, page_size, ExpectedExceptionResponse)


@router.get("/expected-exceptions/{exception_id}", response_model=ExpectedExceptionResponse)
def expected_exception(
    exception_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("expected_exceptions.view"))],
) -> ExpectedExceptionResponse:
    item = session.scalar(
        select(ExpectedException).where(
            ExpectedException.id == exception_id, ExpectedException.tenant_id == context.tenant.id
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Expected exception not found")
    return ExpectedExceptionResponse.model_validate(item)


def _scenario(session: Session, item: DefectScenario, include_rules: bool) -> ScenarioResponse:
    rules = list(
        session.scalars(
            select(DefectScenarioRule)
            .where(DefectScenarioRule.defect_scenario_id == item.id)
            .order_by(DefectScenarioRule.rule_order)
        )
    )
    enabled = [rule for rule in rules if rule.is_enabled]
    severity: dict[str, int] = {}
    for rule in enabled:
        severity[rule.severity] = severity.get(rule.severity, 0) + (rule.requested_count or 0)
    response = ScenarioResponse.model_validate(item)
    return response.model_copy(
        update={
            "enabled_rule_count": len(enabled),
            "expected_approximate_defect_count": sum(rule.requested_count or 0 for rule in enabled),
            "severity_distribution": severity,
            "rules": [ScenarioRuleResponse.model_validate(rule) for rule in rules]
            if include_rules
            else [],
        }
    )


@router.get("/defect-scenarios", response_model=list[ScenarioResponse])
def scenarios(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("defect_scenarios.view"))],
) -> list[ScenarioResponse]:
    items = session.scalars(
        select(DefectScenario)
        .where(DefectScenario.tenant_id == context.tenant.id)
        .order_by(DefectScenario.code, DefectScenario.version)
    ).all()
    return [_scenario(session, item, False) for item in items]


@router.get("/defect-scenarios/{scenario_id}", response_model=ScenarioResponse)
def scenario(
    scenario_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("defect_scenarios.view"))],
) -> ScenarioResponse:
    item = session.scalar(
        select(DefectScenario).where(
            DefectScenario.id == scenario_id, DefectScenario.tenant_id == context.tenant.id
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Defect scenario not found")
    return _scenario(session, item, True)


@router.get("/messy-datasets/{run_id}/control-totals", response_model=GeneratedPage)
def controls(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("messy_controls.view"))],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    _owned(session, context.tenant.id, run_id)
    return _page(
        session,
        MessyGenerationControlTotal,
        [
            MessyGenerationControlTotal.tenant_id == context.tenant.id,
            MessyGenerationControlTotal.messy_dataset_run_id == run_id,
        ],
        page,
        page_size,
        MessyControlResponse,
    )
