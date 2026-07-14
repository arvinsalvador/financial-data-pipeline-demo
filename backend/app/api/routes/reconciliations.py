from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    BankAccount,
    BankLedgerReconciliationRun,
    ReconciliationCandidate,
    ReconciliationControlTotal,
    ReconciliationException,
    ReconciliationMatchGroup,
    ReconciliationReport,
    ReconciliationRule,
)
from app.schemas.generation import GeneratedPage
from app.schemas.reconciliation import (
    BankAccountResponse,
    CandidateResponse,
    ControlResponse,
    DecisionRequest,
    DecisionResponse,
    ExceptionResponse,
    GroupResponse,
    ReconciliationRunResponse,
    ReportResponse,
    ReviewRequest,
    RunReconciliationRequest,
)
from app.services.bank_ledger_reconciliation import (
    BankLedgerReconciliationEngine,
    ReconciliationError,
)
from app.services.governance import AuditService
from app.services.reconciliation_decisions import decide_group

router = APIRouter(prefix="/reconciliations/bank-ledger")
match_group_router = APIRouter(prefix="/reconciliation-match-groups")


def _run(session: Session, tenant_id: int, run_id: int) -> BankLedgerReconciliationRun:
    value = session.scalar(
        select(BankLedgerReconciliationRun).where(
            BankLedgerReconciliationRun.id == run_id,
            BankLedgerReconciliationRun.tenant_id == tenant_id,
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    return value


def _page(
    session: Session,
    model: Any,
    conditions: list[Any],
    schema: Any,
    page: int,
    page_size: int,
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


@router.get("/accounts", response_model=list[BankAccountResponse])
def accounts(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.view"))
    ],
) -> list[BankAccountResponse]:
    return [
        BankAccountResponse.model_validate(item)
        for item in session.scalars(
            select(BankAccount)
            .where(BankAccount.tenant_id == context.tenant.id)
            .order_by(BankAccount.id)
        )
    ]


@router.post("", response_model=ReconciliationRunResponse)
def execute(
    body: RunReconciliationRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.execute"))
    ],
) -> ReconciliationRunResponse:
    try:
        run, no_op = BankLedgerReconciliationEngine(settings).run(
            session,
            context.tenant,
            body.bank_account_id,
            body.date_from,
            body.date_to,
            body.generated_dataset_run_id,
            body.force_rerun,
        )
    except (ReconciliationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    AuditService().record(
        session,
        context,
        event_type="bank_ledger_reconciliation.completed",
        entity_type="bank_ledger_reconciliation_run",
        entity_id=run.id,
        action="execute",
        description="Bank-to-ledger reconciliation completed",
        pipeline_run_id=run.pipeline_run_id,
        metadata={"no_op": no_op, "reconciliation_rate": str(run.reconciliation_rate)},
    )
    session.commit()
    return ReconciliationRunResponse.model_validate(run).model_copy(update={"no_op": no_op})


@router.get("", response_model=GeneratedPage)
@router.get("/runs", response_model=GeneratedPage, include_in_schema=False)
def runs(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.view"))
    ],
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    conditions: list[Any] = [BankLedgerReconciliationRun.tenant_id == context.tenant.id]
    if status:
        conditions.append(BankLedgerReconciliationRun.status == status)
    if date_from:
        conditions.append(BankLedgerReconciliationRun.date_to >= date_from)
    if date_to:
        conditions.append(BankLedgerReconciliationRun.date_from <= date_to)
    return _page(
        session, BankLedgerReconciliationRun, conditions, ReconciliationRunResponse, page, page_size
    )


@router.get("/{run_id}", response_model=ReconciliationRunResponse)
@router.get("/runs/{run_id}", response_model=ReconciliationRunResponse, include_in_schema=False)
def run_detail(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.view"))
    ],
) -> ReconciliationRunResponse:
    return ReconciliationRunResponse.model_validate(_run(session, context.tenant.id, run_id))


@router.get("/{run_id}/candidates", response_model=GeneratedPage)
@router.get("/runs/{run_id}/candidates", response_model=GeneratedPage, include_in_schema=False)
def candidates(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("reconciliation_candidates.view"))
    ],
    status: str | None = None,
    candidate_type: str | None = None,
    rule_code: str | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    bank_transaction_id: int | None = None,
    ledger_record_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GeneratedPage:
    _run(session, context.tenant.id, run_id)
    conditions: list[Any] = [ReconciliationCandidate.reconciliation_run_id == run_id]
    if status:
        conditions.append(ReconciliationCandidate.candidate_status == status)
    if candidate_type:
        conditions.append(ReconciliationCandidate.candidate_type == candidate_type)
    if rule_code:
        conditions.append(
            ReconciliationCandidate.reconciliation_rule_id.in_(
                select(ReconciliationRule.id).where(ReconciliationRule.code == rule_code)
            )
        )
    if confidence_min is not None:
        conditions.append(ReconciliationCandidate.total_confidence >= confidence_min)
    if confidence_max is not None:
        conditions.append(ReconciliationCandidate.total_confidence <= confidence_max)
    if bank_transaction_id is not None:
        conditions.append(ReconciliationCandidate.bank_transaction_id == bank_transaction_id)
    if ledger_record_id is not None:
        conditions.append(ReconciliationCandidate.ledger_record_id == ledger_record_id)
    return _page(session, ReconciliationCandidate, conditions, CandidateResponse, page, page_size)


@router.get("/{run_id}/match-groups", response_model=GeneratedPage)
@router.get("/runs/{run_id}/groups", response_model=GeneratedPage, include_in_schema=False)
def groups(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
    status: str | None = None,
    group_type: str | None = None,
    confidence_min: float | None = None,
    auto_accepted: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GeneratedPage:
    _run(session, context.tenant.id, run_id)
    conditions: list[Any] = [ReconciliationMatchGroup.reconciliation_run_id == run_id]
    if status:
        conditions.append(ReconciliationMatchGroup.status == status)
    if group_type:
        conditions.append(ReconciliationMatchGroup.group_type == group_type)
    if confidence_min is not None:
        conditions.append(ReconciliationMatchGroup.confidence >= confidence_min)
    if auto_accepted is not None:
        conditions.append(ReconciliationMatchGroup.auto_accepted == auto_accepted)
    return _page(session, ReconciliationMatchGroup, conditions, GroupResponse, page, page_size)


@router.get("/runs/{run_id}/groups/{group_id}", response_model=GroupResponse)
def group_detail(
    run_id: int,
    group_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
) -> GroupResponse:
    _run(session, context.tenant.id, run_id)
    group = session.scalar(
        select(ReconciliationMatchGroup).where(
            ReconciliationMatchGroup.id == group_id,
            ReconciliationMatchGroup.reconciliation_run_id == run_id,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="Match group not found")
    return GroupResponse.model_validate(group)


@router.post("/runs/{run_id}/groups/{group_id}/decisions", response_model=DecisionResponse)
def decision(
    run_id: int,
    group_id: int,
    body: DecisionRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
) -> DecisionResponse:
    run = _run(session, context.tenant.id, run_id)
    group = session.scalar(
        select(ReconciliationMatchGroup).where(
            ReconciliationMatchGroup.id == group_id,
            ReconciliationMatchGroup.reconciliation_run_id == run_id,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="Match group not found")
    try:
        record = decide_group(
            session, run, group, context.actor.id, body.decision, body.reason, body.notes
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    BankLedgerReconciliationEngine(settings).refresh_controls(session, run)
    AuditService().record(
        session,
        context,
        event_type=f"reconciliation.group_{body.decision}",
        entity_type="reconciliation_match_group",
        entity_id=group.id,
        action=body.decision,
        description=f"Reconciliation group {body.decision}",
        pipeline_run_id=run.pipeline_run_id,
        metadata={"reason": body.reason, "new_status": record.new_status},
    )
    session.commit()
    return DecisionResponse.model_validate(record)


@router.get("/{run_id}/exceptions", response_model=GeneratedPage)
@router.get("/runs/{run_id}/exceptions", response_model=GeneratedPage, include_in_schema=False)
def exceptions(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("reconciliation_exceptions.view"))
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GeneratedPage:
    _run(session, context.tenant.id, run_id)
    return _page(
        session,
        ReconciliationException,
        [ReconciliationException.reconciliation_run_id == run_id],
        ExceptionResponse,
        page,
        page_size,
    )


@router.get("/{run_id}/control-totals", response_model=list[ControlResponse])
@router.get(
    "/runs/{run_id}/controls", response_model=list[ControlResponse], include_in_schema=False
)
def controls(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("reconciliation_controls.view"))],
) -> list[ControlResponse]:
    _run(session, context.tenant.id, run_id)
    return [
        ControlResponse.model_validate(item)
        for item in session.scalars(
            select(ReconciliationControlTotal)
            .where(ReconciliationControlTotal.reconciliation_run_id == run_id)
            .order_by(ReconciliationControlTotal.control_name)
        )
    ]


@router.get("/{run_id}/unmatched-bank", response_model=GeneratedPage)
@router.get("/runs/{run_id}/unmatched-bank", response_model=GeneratedPage, include_in_schema=False)
def unmatched_bank(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("reconciliation_exceptions.view"))
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GeneratedPage:
    _run(session, context.tenant.id, run_id)
    return _page(
        session,
        ReconciliationException,
        [
            ReconciliationException.reconciliation_run_id == run_id,
            ReconciliationException.exception_code == "unmatched_bank_transaction",
        ],
        ExceptionResponse,
        page,
        page_size,
    )


@router.get("/{run_id}/unmatched-ledger", response_model=GeneratedPage)
@router.get(
    "/runs/{run_id}/unmatched-ledger", response_model=GeneratedPage, include_in_schema=False
)
def unmatched_ledger(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("reconciliation_exceptions.view"))
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GeneratedPage:
    _run(session, context.tenant.id, run_id)
    return _page(
        session,
        ReconciliationException,
        [
            ReconciliationException.reconciliation_run_id == run_id,
            ReconciliationException.exception_code == "unmatched_ledger_entry",
        ],
        ExceptionResponse,
        page,
        page_size,
    )


@router.get("/{run_id}/reports", response_model=list[ReportResponse])
@router.get("/runs/{run_id}/reports", response_model=list[ReportResponse], include_in_schema=False)
def reports(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("reconciliation_reports.view"))],
) -> list[ReportResponse]:
    _run(session, context.tenant.id, run_id)
    return [
        ReportResponse.model_validate(item)
        for item in session.scalars(
            select(ReconciliationReport)
            .where(ReconciliationReport.reconciliation_run_id == run_id)
            .order_by(ReconciliationReport.report_type)
        )
    ]


def _owned_group(
    session: Session, tenant_id: int, group_id: int
) -> tuple[BankLedgerReconciliationRun, ReconciliationMatchGroup]:
    group = session.scalar(
        select(ReconciliationMatchGroup).where(
            ReconciliationMatchGroup.id == group_id,
            ReconciliationMatchGroup.tenant_id == tenant_id,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="Match group not found")
    return _run(session, tenant_id, group.reconciliation_run_id), group


@match_group_router.get("/{group_id}", response_model=GroupResponse)
def standalone_group_detail(
    group_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
) -> GroupResponse:
    _, group = _owned_group(session, context.tenant.id, group_id)
    return GroupResponse.model_validate(group)


def _review_action(
    action: str,
    group_id: int,
    body: ReviewRequest,
    session: Session,
    settings: Settings,
    context: RequestContext,
) -> DecisionResponse:
    run, group = _owned_group(session, context.tenant.id, group_id)
    try:
        record = decide_group(
            session, run, group, context.actor.id, action, body.reason, body.notes
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    BankLedgerReconciliationEngine(settings).refresh_controls(session, run)
    AuditService().record(
        session,
        context,
        event_type=f"reconciliation.group_{action}",
        entity_type="reconciliation_match_group",
        entity_id=group.id,
        action=action,
        description=f"Reconciliation group {action}",
        pipeline_run_id=run.pipeline_run_id,
        metadata={"reason": body.reason, "new_status": record.new_status},
    )
    session.commit()
    return DecisionResponse.model_validate(record)


@match_group_router.post("/{group_id}/accept", response_model=DecisionResponse)
def accept_group(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
) -> DecisionResponse:
    return _review_action("accept", group_id, body, session, settings, context)


@match_group_router.post("/{group_id}/reject", response_model=DecisionResponse)
def reject_group(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
) -> DecisionResponse:
    return _review_action("reject", group_id, body, session, settings, context)


@match_group_router.post("/{group_id}/resolve", response_model=DecisionResponse)
def resolve_group(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
) -> DecisionResponse:
    return _review_action("resolve", group_id, body, session, settings, context)


@match_group_router.post("/{group_id}/reopen", response_model=DecisionResponse)
def reopen_group(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("bank_ledger_reconciliation.review"))
    ],
) -> DecisionResponse:
    return _review_action("reopen", group_id, body, session, settings, context)
