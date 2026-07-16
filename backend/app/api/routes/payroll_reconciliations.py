from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    BankAccount,
    PayrollReconciliationCandidate,
    PayrollReconciliationControlTotal,
    PayrollReconciliationDecision,
    PayrollReconciliationException,
    PayrollReconciliationGroup,
    PayrollReconciliationMatch,
    PayrollReconciliationReport,
    PayrollReconciliationRun,
    PayrollRun,
)
from app.schemas.generation import GeneratedPage
from app.schemas.payroll_reconciliation import (
    PayrollCandidateResponse,
    PayrollControlResponse,
    PayrollDecisionResponse,
    PayrollExceptionResponse,
    PayrollGroupResponse,
    PayrollReconciliationRunResponse,
    PayrollReportResponse,
    PayrollReviewRequest,
    PayrollRunDetailResponse,
    RunPayrollReconciliationRequest,
)
from app.schemas.reconciliation import BankAccountResponse
from app.services.governance import AuditService
from app.services.payroll_reconciliation import (
    PayrollReconciliationEngine,
    PayrollReconciliationError,
)

router = APIRouter(prefix="/reconciliations/payroll")
group_router = APIRouter(prefix="/payroll-reconciliation-groups")


def owned_run(session: Session, tenant_id: int, run_id: int) -> PayrollReconciliationRun:
    value = session.scalar(
        select(PayrollReconciliationRun).where(
            PayrollReconciliationRun.id == run_id, PayrollReconciliationRun.tenant_id == tenant_id
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="Payroll reconciliation run not found")
    return value


def page(
    session: Session, model: Any, conditions: list[Any], schema: Any, number: int, size: int
) -> GeneratedPage:
    total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    values = session.scalars(
        select(model).where(*conditions).order_by(model.id).offset((number - 1) * size).limit(size)
    ).all()
    return GeneratedPage(
        items=[schema.model_validate(item) for item in values],
        total=total,
        page=number,
        page_size=size,
    )


@router.post("", response_model=PayrollReconciliationRunResponse)
def execute(
    body: RunPayrollReconciliationRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation.execute"))
    ],
) -> PayrollReconciliationRunResponse:
    AuditService().record(
        session,
        context,
        event_type="payroll_reconciliation.requested",
        entity_type="payroll_reconciliation_run",
        entity_id=None,
        action="execute",
        description="Payroll reconciliation requested",
        metadata={
            "account": body.payroll_bank_account_id,
            "date_from": str(body.date_from),
            "date_to": str(body.date_to),
            "settlement_model": body.settlement_model,
            "force_rerun": body.force_rerun,
        },
    )
    session.commit()
    try:
        run, no_op = PayrollReconciliationEngine(settings).run(
            session,
            context.tenant,
            body.payroll_bank_account_id,
            body.date_from,
            body.date_to,
            body.settlement_model,
            body.force_rerun,
        )
    except PayrollReconciliationError as error:
        session.rollback()
        AuditService().record(
            session,
            context,
            event_type="payroll_reconciliation.failed",
            entity_type="payroll_reconciliation_run",
            entity_id=None,
            action="execute",
            description="Payroll reconciliation failed validation",
            metadata={"error_type": type(error).__name__},
        )
        session.commit()
        raise HTTPException(status_code=422, detail=str(error)) from error
    if body.force_rerun:
        AuditService().record(
            session,
            context,
            event_type="payroll_reconciliation.forced_rerun",
            entity_type="payroll_reconciliation_run",
            entity_id=run.id,
            action="execute",
            description="Forced payroll reconciliation requested",
            pipeline_run_id=run.pipeline_run_id,
            metadata={"no_op": no_op},
        )
    AuditService().record(
        session,
        context,
        event_type=(
            "payroll_reconciliation.no_op"
            if no_op
            else "payroll_reconciliation.completed_with_exceptions"
            if run.exception_count
            else "payroll_reconciliation.completed"
        ),
        entity_type="payroll_reconciliation_run",
        entity_id=run.id,
        action="execute",
        description="Payroll reconciliation completed",
        pipeline_run_id=run.pipeline_run_id,
        metadata={"no_op": no_op, "status": run.status, "rate": str(run.reconciliation_rate)},
    )
    session.commit()
    return PayrollReconciliationRunResponse.model_validate(run).model_copy(update={"no_op": no_op})


@router.get("", response_model=GeneratedPage)
def history(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("payroll_reconciliation.view"))],
    page_number: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    return page(
        session,
        PayrollReconciliationRun,
        [PayrollReconciliationRun.tenant_id == context.tenant.id],
        PayrollReconciliationRunResponse,
        page_number,
        page_size,
    )


@router.get("/accounts", response_model=list[BankAccountResponse])
def accounts(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("payroll_reconciliation.view"))],
) -> list[BankAccountResponse]:
    return [
        BankAccountResponse.model_validate(item)
        for item in session.scalars(
            select(BankAccount)
            .where(
                BankAccount.tenant_id == context.tenant.id, BankAccount.account_type == "payroll"
            )
            .order_by(BankAccount.id)
        )
    ]


@router.get("/{run_id}", response_model=PayrollReconciliationRunResponse)
def detail(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("payroll_reconciliation.view"))],
) -> PayrollReconciliationRunResponse:
    return PayrollReconciliationRunResponse.model_validate(
        owned_run(session, context.tenant.id, run_id)
    )


@router.get("/{run_id}/payroll-runs", response_model=GeneratedPage)
def payroll_runs(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("payroll_reconciliation.view"))],
    page_number: int = 1,
    page_size: int = 100,
) -> GeneratedPage:
    run = owned_run(session, context.tenant.id, run_id)
    return page(
        session,
        PayrollRun,
        [
            PayrollRun.tenant_id == context.tenant.id,
            PayrollRun.pay_date >= run.date_from,
            PayrollRun.pay_date <= run.date_to,
        ],
        PayrollRunDetailResponse,
        page_number,
        page_size,
    )


@router.get("/{run_id}/payroll-runs/{payroll_run_id}", response_model=PayrollRunDetailResponse)
def payroll_run_detail(
    run_id: int,
    payroll_run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_permission("payroll_reconciliation.view"))],
) -> PayrollRunDetailResponse:
    owned_run(session, context.tenant.id, run_id)
    value = session.scalar(
        select(PayrollRun).where(
            PayrollRun.id == payroll_run_id, PayrollRun.tenant_id == context.tenant.id
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return PayrollRunDetailResponse.model_validate(value)


@router.get("/{run_id}/candidates", response_model=GeneratedPage)
def candidates(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation_candidates.view"))
    ],
    payroll_run_id: int | None = None,
    candidate_type: str | None = None,
    status: str | None = None,
    bank_transaction_id: int | None = None,
    gl_record_id: str | None = None,
    confidence_min: float | None = None,
    page_number: int = 1,
    page_size: int = 100,
) -> GeneratedPage:
    owned_run(session, context.tenant.id, run_id)
    conditions: list[Any] = [PayrollReconciliationCandidate.payroll_reconciliation_run_id == run_id]
    for value, column in (
        (payroll_run_id, PayrollReconciliationCandidate.payroll_run_id),
        (candidate_type, PayrollReconciliationCandidate.candidate_type),
        (status, PayrollReconciliationCandidate.candidate_status),
        (bank_transaction_id, PayrollReconciliationCandidate.bank_transaction_id),
        (gl_record_id, PayrollReconciliationCandidate.gl_record_id),
    ):
        if value is not None:
            conditions.append(column == value)
    if confidence_min is not None:
        conditions.append(PayrollReconciliationCandidate.total_confidence >= confidence_min)
    return page(
        session,
        PayrollReconciliationCandidate,
        conditions,
        PayrollCandidateResponse,
        page_number,
        page_size,
    )


@router.get("/{run_id}/groups", response_model=GeneratedPage)
def groups(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation.review"))
    ],
    status: str | None = None,
    page_number: int = 1,
    page_size: int = 100,
) -> GeneratedPage:
    owned_run(session, context.tenant.id, run_id)
    conditions: list[Any] = [PayrollReconciliationGroup.payroll_reconciliation_run_id == run_id]
    if status:
        conditions.append(PayrollReconciliationGroup.status == status)
    return page(
        session,
        PayrollReconciliationGroup,
        conditions,
        PayrollGroupResponse,
        page_number,
        page_size,
    )


def collection(
    run_id: int,
    model: Any,
    schema: Any,
    session: Session,
    context: RequestContext,
    code: str | None = None,
) -> GeneratedPage:
    owned_run(session, context.tenant.id, run_id)
    conditions = [model.payroll_reconciliation_run_id == run_id]
    if code:
        conditions.append(model.exception_code == code)
    return page(session, model, conditions, schema, 1, 500)


@router.get("/{run_id}/exceptions", response_model=GeneratedPage)
def exceptions(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation_exceptions.view"))
    ],
) -> GeneratedPage:
    return collection(
        run_id, PayrollReconciliationException, PayrollExceptionResponse, session, context
    )


@router.get("/{run_id}/unmatched-payroll", response_model=GeneratedPage)
def unmatched_payroll(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation_exceptions.view"))
    ],
) -> GeneratedPage:
    return collection(
        run_id,
        PayrollReconciliationException,
        PayrollExceptionResponse,
        session,
        context,
        "unmatched_payroll_run",
    )


@router.get("/{run_id}/unmatched-bank", response_model=GeneratedPage)
def unmatched_bank(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation_exceptions.view"))
    ],
) -> GeneratedPage:
    return collection(
        run_id,
        PayrollReconciliationException,
        PayrollExceptionResponse,
        session,
        context,
        "unmatched_bank_withdrawal",
    )


@router.get("/{run_id}/unmatched-gl", response_model=GeneratedPage)
def unmatched_gl(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation_exceptions.view"))
    ],
) -> GeneratedPage:
    return collection(
        run_id,
        PayrollReconciliationException,
        PayrollExceptionResponse,
        session,
        context,
        "unmatched_payroll_gl",
    )


@router.get("/{run_id}/control-totals", response_model=list[PayrollControlResponse])
def controls(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation_controls.view"))
    ],
) -> list[PayrollControlResponse]:
    owned_run(session, context.tenant.id, run_id)
    return [
        PayrollControlResponse.model_validate(item)
        for item in session.scalars(
            select(PayrollReconciliationControlTotal)
            .where(PayrollReconciliationControlTotal.payroll_reconciliation_run_id == run_id)
            .order_by(PayrollReconciliationControlTotal.control_name)
        )
    ]


@router.get("/{run_id}/reports", response_model=list[PayrollReportResponse])
def reports(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation_reports.view"))
    ],
) -> list[PayrollReportResponse]:
    owned_run(session, context.tenant.id, run_id)
    return [
        PayrollReportResponse.model_validate(item)
        for item in session.scalars(
            select(PayrollReconciliationReport)
            .where(PayrollReconciliationReport.payroll_reconciliation_run_id == run_id)
            .order_by(PayrollReconciliationReport.report_type)
        )
    ]


def owned_group(
    session: Session, tenant_id: int, group_id: int
) -> tuple[PayrollReconciliationRun, PayrollReconciliationGroup]:
    group = session.scalar(
        select(PayrollReconciliationGroup).where(
            PayrollReconciliationGroup.id == group_id,
            PayrollReconciliationGroup.tenant_id == tenant_id,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="Payroll reconciliation group not found")
    return owned_run(session, tenant_id, group.payroll_reconciliation_run_id), group


@group_router.get("/{group_id}", response_model=PayrollGroupResponse)
def group_detail(
    group_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation.review"))
    ],
) -> PayrollGroupResponse:
    return PayrollGroupResponse.model_validate(owned_group(session, context.tenant.id, group_id)[1])


def decide(
    action: str,
    group_id: int,
    body: PayrollReviewRequest,
    session: Session,
    context: RequestContext,
) -> PayrollDecisionResponse:
    run, group = owned_group(session, context.tenant.id, group_id)
    transitions = {
        "accept": ({"suggested", "partially_matched", "needs_review", "reopened"}, "matched"),
        "reject": ({"suggested", "partially_matched", "needs_review", "reopened"}, "rejected"),
        "resolve": ({"matched", "partially_matched", "needs_review"}, "resolved"),
        "reopen": ({"matched", "resolved", "rejected"}, "reopened"),
    }
    allowed, target = transitions[action]
    if group.status not in allowed:
        raise HTTPException(
            status_code=409, detail=f"Cannot {action} group in {group.status} status"
        )
    previous = group.status
    now = datetime.now(UTC)
    group.status = target
    group.reviewed_by_user_id = context.actor.id
    group.reviewed_at = now
    group.notes = body.notes
    for match in session.scalars(
        select(PayrollReconciliationMatch).where(
            PayrollReconciliationMatch.reconciliation_group_id == group.id
        )
    ):
        match.status = target
    record = PayrollReconciliationDecision(
        tenant_id=run.tenant_id,
        payroll_reconciliation_run_id=run.id,
        reconciliation_group_id=group.id,
        actor_user_id=context.actor.id,
        decision=action,
        previous_status=previous,
        new_status=target,
        reason=body.reason,
        notes=body.notes,
        metadata_json={},
        decided_at=now,
    )
    session.add(record)
    session.flush()
    AuditService().record(
        session,
        context,
        event_type=f"payroll_reconciliation.group_{action}",
        entity_type="payroll_reconciliation_group",
        entity_id=group.id,
        action=action,
        description=f"Payroll reconciliation group {action}",
        pipeline_run_id=run.pipeline_run_id,
        metadata={"reason": body.reason, "new_status": target},
    )
    session.commit()
    return PayrollDecisionResponse.model_validate(record)


@group_router.post("/{group_id}/accept", response_model=PayrollDecisionResponse)
def accept(
    group_id: int,
    body: PayrollReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation.review"))
    ],
) -> PayrollDecisionResponse:
    return decide("accept", group_id, body, session, context)


@group_router.post("/{group_id}/reject", response_model=PayrollDecisionResponse)
def reject(
    group_id: int,
    body: PayrollReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation.review"))
    ],
) -> PayrollDecisionResponse:
    return decide("reject", group_id, body, session, context)


@group_router.post("/{group_id}/resolve", response_model=PayrollDecisionResponse)
def resolve(
    group_id: int,
    body: PayrollReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation.review"))
    ],
) -> PayrollDecisionResponse:
    return decide("resolve", group_id, body, session, context)


@group_router.post("/{group_id}/reopen", response_model=PayrollDecisionResponse)
def reopen(
    group_id: int,
    body: PayrollReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("payroll_reconciliation.review"))
    ],
) -> PayrollDecisionResponse:
    return decide("reopen", group_id, body, session, context)
