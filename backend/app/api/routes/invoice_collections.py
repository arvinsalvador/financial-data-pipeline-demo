from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import RequestContext, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    AccountsReceivableAgingBucket,
    AccountsReceivableAgingSnapshot,
    BankAccount,
    InvoiceCollectionsCandidate,
    InvoiceCollectionsControlTotal,
    InvoiceCollectionsDecision,
    InvoiceCollectionsException,
    InvoiceCollectionsMatch,
    InvoiceCollectionsMatchGroup,
    InvoiceCollectionsReconciliationRule,
    InvoiceCollectionsReconciliationRun,
    InvoiceCollectionsReport,
)
from app.schemas.generation import GeneratedPage
from app.schemas.invoice_collections import (
    AgingResponse,
    CandidateResponse,
    ControlResponse,
    ExceptionResponse,
    GroupResponse,
    InvoiceCollectionsRunResponse,
    PaymentResponse,
    ReportResponse,
    ReviewRequest,
    RunInvoiceCollectionsRequest,
)
from app.schemas.reconciliation import BankAccountResponse
from app.services.governance import AuditService
from app.services.invoice_collections_reconciliation import (
    InvoiceCollectionsError,
    InvoiceCollectionsReconciliationEngine,
)

router = APIRouter(prefix="/reconciliations/invoice-collections")
group_router = APIRouter(prefix="/invoice-collections-groups")


def owned_run(session: Session, tenant_id: int, run_id: int) -> InvoiceCollectionsReconciliationRun:
    value = session.scalar(
        select(InvoiceCollectionsReconciliationRun).where(
            InvoiceCollectionsReconciliationRun.id == run_id,
            InvoiceCollectionsReconciliationRun.tenant_id == tenant_id,
        )
    )
    if value is None:
        raise HTTPException(
            status_code=404, detail="Invoice collections reconciliation run not found"
        )
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


@router.post("", response_model=InvoiceCollectionsRunResponse)
def execute(
    body: RunInvoiceCollectionsRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.execute"))
    ],
) -> InvoiceCollectionsRunResponse:
    AuditService().record(
        session,
        context,
        event_type="invoice_collections_reconciliation.requested",
        entity_type="invoice_collections_reconciliation_run",
        entity_id=None,
        action="execute",
        description="Invoice and collections reconciliation requested",
        metadata={
            "bank_account_id": body.bank_account_id,
            "date_from": str(body.date_from),
            "date_to": str(body.date_to),
            "aging_as_of_date": str(body.aging_as_of_date),
            "force_rerun": body.force_rerun,
        },
    )
    session.commit()
    try:
        run, no_op = InvoiceCollectionsReconciliationEngine(settings).run(
            session,
            context.tenant,
            body.bank_account_id,
            body.date_from,
            body.date_to,
            body.aging_as_of_date,
            body.force_rerun,
        )
    except InvoiceCollectionsError as error:
        session.rollback()
        AuditService().record(
            session,
            context,
            event_type="invoice_collections_reconciliation.failed",
            entity_type="invoice_collections_reconciliation_run",
            entity_id=None,
            action="execute",
            description="Invoice and collections reconciliation failed validation",
            metadata={"error_type": type(error).__name__},
        )
        session.commit()
        raise HTTPException(status_code=422, detail=str(error)) from error
    if body.force_rerun:
        AuditService().record(
            session,
            context,
            event_type="invoice_collections_reconciliation.forced_rerun",
            entity_type="invoice_collections_reconciliation_run",
            entity_id=run.id,
            action="execute",
            description="Forced invoice collections reconciliation completed",
            pipeline_run_id=run.pipeline_run_id,
            metadata={"no_op": no_op},
        )
    AuditService().record(
        session,
        context,
        event_type="invoice_collections_reconciliation.no_op"
        if no_op
        else "invoice_collections_reconciliation.completed_with_exceptions"
        if run.exception_count
        else "invoice_collections_reconciliation.completed",
        entity_type="invoice_collections_reconciliation_run",
        entity_id=run.id,
        action="execute",
        description="Invoice and collections reconciliation completed",
        pipeline_run_id=run.pipeline_run_id,
        metadata={"no_op": no_op, "status": run.status},
    )
    session.commit()
    return InvoiceCollectionsRunResponse.model_validate(run).model_copy(update={"no_op": no_op})


@router.get("", response_model=GeneratedPage)
def history(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
    page_number: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GeneratedPage:
    return page(
        session,
        InvoiceCollectionsReconciliationRun,
        [InvoiceCollectionsReconciliationRun.tenant_id == context.tenant.id],
        InvoiceCollectionsRunResponse,
        page_number,
        page_size,
    )


@router.get("/accounts", response_model=list[BankAccountResponse])
def accounts(
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
) -> list[BankAccountResponse]:
    return [
        BankAccountResponse.model_validate(item)
        for item in session.scalars(
            select(BankAccount)
            .where(
                BankAccount.tenant_id == context.tenant.id, BankAccount.account_type != "payroll"
            )
            .order_by(BankAccount.id)
        )
    ]


@router.get("/{run_id}", response_model=InvoiceCollectionsRunResponse)
def detail(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
) -> InvoiceCollectionsRunResponse:
    return InvoiceCollectionsRunResponse.model_validate(
        owned_run(session, context.tenant.id, run_id)
    )


def run_page(
    run_id: int,
    model: Any,
    schema: Any,
    session: Session,
    context: RequestContext,
    permission_filter: Any | None = None,
    page_number: int = 1,
    page_size: int = 100,
) -> GeneratedPage:
    owned_run(session, context.tenant.id, run_id)
    conditions = [model.reconciliation_run_id == run_id]
    if permission_filter is not None:
        conditions.append(permission_filter)
    return page(session, model, conditions, schema, page_number, page_size)


@router.get("/{run_id}/invoices", response_model=GeneratedPage)
@router.get("/{run_id}/groups", response_model=GeneratedPage)
def groups(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
    page_number: int = 1,
    page_size: int = 100,
) -> GeneratedPage:
    return run_page(
        run_id,
        InvoiceCollectionsMatchGroup,
        GroupResponse,
        session,
        context,
        page_number=page_number,
        page_size=page_size,
    )


def payment_values(session: Session, run_id: int) -> list[PaymentResponse]:
    matches = list(
        session.scalars(
            select(InvoiceCollectionsMatch)
            .where(
                InvoiceCollectionsMatch.reconciliation_run_id == run_id,
                InvoiceCollectionsMatch.payment_id.is_not(None),
            )
            .order_by(InvoiceCollectionsMatch.payment_id, InvoiceCollectionsMatch.id)
        )
    )
    by_payment: dict[str, list[InvoiceCollectionsMatch]] = {}
    for match in matches:
        if match.payment_id:
            by_payment.setdefault(match.payment_id, []).append(match)
    result: list[PaymentResponse] = []
    for payment_id, values in sorted(by_payment.items()):
        payment = (values[0].metadata_json or {}).get("payment") or {}
        invoices = sorted({item.invoice_id for item in values if item.invoice_id})
        applied = sum((item.matched_amount for item in values), 0)
        amount = payment.get("payment_amount", applied)
        bank_id = next(
            (item.bank_transaction_id for item in values if item.bank_transaction_id), None
        )
        group_statuses = {item.status for item in values}
        result.append(
            PaymentResponse(
                payment_id=payment_id,
                payment_reference=payment.get("payment_reference", payment_id),
                customer_id=payment.get("customer_id", values[0].customer_id or ""),
                payment_date=payment.get("payment_date"),
                payment_amount=amount,
                applied_amount=applied,
                unapplied_amount=payment.get("unapplied_amount", 0),
                invoice_count=len(invoices),
                bank_transaction_id=bank_id,
                deposit_status="matched" if bank_id else "unmatched",
                gl_status="matched"
                if all(item.status == "matched" for item in values)
                else "review",
                overall_status="matched" if group_statuses == {"matched"} else "needs_review",
                invoice_ids=invoices,
            )
        )
    return result


@router.get("/{run_id}/payments", response_model=GeneratedPage)
def payments(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
    customer: str | None = None,
    status: str | None = None,
    page_number: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> GeneratedPage:
    owned_run(session, context.tenant.id, run_id)
    values = payment_values(session, run_id)
    if customer:
        values = [item for item in values if item.customer_id == customer]
    if status:
        values = [item for item in values if item.overall_status == status]
    start = (page_number - 1) * page_size
    return GeneratedPage(
        items=values[start : start + page_size],
        total=len(values),
        page=page_number,
        page_size=page_size,
    )


@router.get("/{run_id}/payments/{payment_id}", response_model=PaymentResponse)
def payment_detail(
    run_id: int,
    payment_id: str,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
) -> PaymentResponse:
    owned_run(session, context.tenant.id, run_id)
    value = next(
        (item for item in payment_values(session, run_id) if item.payment_id == payment_id), None
    )
    if value is None:
        raise HTTPException(status_code=404, detail="Payment reconciliation detail not found")
    return value


@router.get("/{run_id}/invoices/{invoice_id}", response_model=GroupResponse)
def invoice_detail(
    run_id: int,
    invoice_id: str,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
) -> GroupResponse:
    owned_run(session, context.tenant.id, run_id)
    value = session.scalar(
        select(InvoiceCollectionsMatchGroup).where(
            InvoiceCollectionsMatchGroup.reconciliation_run_id == run_id,
            InvoiceCollectionsMatchGroup.metadata_json["invoice"]["invoice_id"].astext
            == invoice_id,
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="Invoice reconciliation detail not found")
    return GroupResponse.model_validate(value)


@router.get("/{run_id}/candidates", response_model=GeneratedPage)
def candidates(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_candidates.view"))
    ],
    page_number: int = 1,
    page_size: int = 100,
    customer: str | None = None,
    deal: str | None = None,
    invoice: str | None = None,
    payment: str | None = None,
    deposit: int | None = None,
    gl_record: str | None = None,
    candidate_type: str | None = None,
    rule_code: str | None = None,
    status: str | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
) -> GeneratedPage:
    owned_run(session, context.tenant.id, run_id)
    conditions: list[Any] = [InvoiceCollectionsCandidate.reconciliation_run_id == run_id]
    for value, column in (
        (customer, InvoiceCollectionsCandidate.customer_id),
        (deal, InvoiceCollectionsCandidate.crm_deal_id),
        (invoice, InvoiceCollectionsCandidate.invoice_id),
        (payment, InvoiceCollectionsCandidate.payment_id),
        (deposit, InvoiceCollectionsCandidate.bank_transaction_id),
        (gl_record, InvoiceCollectionsCandidate.gl_record_id),
        (candidate_type, InvoiceCollectionsCandidate.candidate_type),
        (status, InvoiceCollectionsCandidate.candidate_status),
    ):
        if value is not None:
            conditions.append(column == value)
    if rule_code:
        rule_id = session.scalar(
            select(InvoiceCollectionsReconciliationRule.id).where(
                InvoiceCollectionsReconciliationRule.tenant_id == context.tenant.id,
                InvoiceCollectionsReconciliationRule.code == rule_code,
            )
        )
        conditions.append(InvoiceCollectionsCandidate.reconciliation_rule_id == (rule_id or -1))
    if confidence_min is not None:
        conditions.append(InvoiceCollectionsCandidate.total_confidence >= confidence_min)
    if confidence_max is not None:
        conditions.append(InvoiceCollectionsCandidate.total_confidence <= confidence_max)
    return page(
        session, InvoiceCollectionsCandidate, conditions, CandidateResponse, page_number, page_size
    )


@router.get("/{run_id}/exceptions", response_model=GeneratedPage)
def exceptions(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_exceptions.view"))
    ],
    code: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    invoice: str | None = None,
    payment: str | None = None,
    page_number: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> GeneratedPage:
    owned_run(session, context.tenant.id, run_id)
    conditions: list[Any] = [InvoiceCollectionsException.reconciliation_run_id == run_id]
    for value, column in (
        (code, InvoiceCollectionsException.exception_code),
        (severity, InvoiceCollectionsException.severity),
        (status, InvoiceCollectionsException.status),
        (invoice, InvoiceCollectionsException.invoice_id),
        (payment, InvoiceCollectionsException.payment_id),
    ):
        if value is not None:
            conditions.append(column == value)
    return page(
        session,
        InvoiceCollectionsException,
        conditions,
        ExceptionResponse,
        page_number,
        page_size,
    )


@router.get("/{run_id}/unmatched-invoices", response_model=GeneratedPage)
def unmatched_invoices(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_exceptions.view"))
    ],
) -> GeneratedPage:
    return run_page(
        run_id,
        InvoiceCollectionsMatchGroup,
        GroupResponse,
        session,
        context,
        InvoiceCollectionsMatchGroup.status == "unmatched",
        1,
        500,
    )


@router.get("/{run_id}/unmatched-payments", response_model=GeneratedPage)
def unmatched_payments(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_exceptions.view"))
    ],
) -> GeneratedPage:
    return run_page(
        run_id,
        InvoiceCollectionsException,
        ExceptionResponse,
        session,
        context,
        InvoiceCollectionsException.exception_code.in_(("unmatched_payment", "unapplied_payment")),
        1,
        500,
    )


@router.get("/{run_id}/unmatched-deposits", response_model=GeneratedPage)
def unmatched_deposits(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_exceptions.view"))
    ],
) -> GeneratedPage:
    return run_page(
        run_id,
        InvoiceCollectionsException,
        ExceptionResponse,
        session,
        context,
        InvoiceCollectionsException.exception_code == "unmatched_bank_deposit",
        1,
        500,
    )


@router.get("/{run_id}/unmatched-gl", response_model=GeneratedPage)
def unmatched_gl(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_exceptions.view"))
    ],
) -> GeneratedPage:
    return run_page(
        run_id,
        InvoiceCollectionsException,
        ExceptionResponse,
        session,
        context,
        InvoiceCollectionsException.exception_code == "unmatched_ar_gl",
        1,
        500,
    )


@router.get("/{run_id}/control-totals", response_model=list[ControlResponse])
def controls(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_controls.view"))
    ],
) -> list[ControlResponse]:
    owned_run(session, context.tenant.id, run_id)
    return [
        ControlResponse.model_validate(item)
        for item in session.scalars(
            select(InvoiceCollectionsControlTotal)
            .where(InvoiceCollectionsControlTotal.reconciliation_run_id == run_id)
            .order_by(InvoiceCollectionsControlTotal.control_name)
        )
    ]


@router.get("/{run_id}/ar-aging", response_model=list[AgingResponse])
def ar_aging(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("accounts_receivable_aging.view"))
    ],
) -> list[AgingResponse]:
    owned_run(session, context.tenant.id, run_id)
    return [
        AgingResponse.model_validate(item)
        for item in session.scalars(
            select(AccountsReceivableAgingSnapshot)
            .where(AccountsReceivableAgingSnapshot.reconciliation_run_id == run_id)
            .order_by(AccountsReceivableAgingSnapshot.customer_id)
        )
    ]


@router.get("/{run_id}/ar-aging/customers/{customer_id}")
def ar_aging_customer(
    run_id: int,
    customer_id: str,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("accounts_receivable_aging.view"))
    ],
) -> dict[str, Any]:
    owned_run(session, context.tenant.id, run_id)
    snapshot = session.scalar(
        select(AccountsReceivableAgingSnapshot).where(
            AccountsReceivableAgingSnapshot.reconciliation_run_id == run_id,
            AccountsReceivableAgingSnapshot.customer_id == customer_id,
        )
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Customer AR aging snapshot not found")
    buckets = list(
        session.scalars(
            select(AccountsReceivableAgingBucket)
            .where(
                AccountsReceivableAgingBucket.aging_snapshot_id == snapshot.id,
                AccountsReceivableAgingBucket.tenant_id == context.tenant.id,
            )
            .order_by(AccountsReceivableAgingBucket.due_date, AccountsReceivableAgingBucket.id)
        )
    )
    return {
        "snapshot": AgingResponse.model_validate(snapshot).model_dump(mode="json"),
        "invoices": [
            {
                "invoice_id": item.invoice_id,
                "invoice_date": item.invoice_date,
                "due_date": item.due_date,
                "days_outstanding": item.days_outstanding,
                "aging_bucket": item.aging_bucket,
                "original_amount": item.original_amount,
                "applied_payment_amount": item.applied_payment_amount,
                "outstanding_amount": item.outstanding_amount,
                "status": item.status,
            }
            for item in buckets
        ],
    }


@router.get("/{run_id}/reports", response_model=list[ReportResponse])
def reports(
    run_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reports.view"))
    ],
) -> list[ReportResponse]:
    owned_run(session, context.tenant.id, run_id)
    return [
        ReportResponse.model_validate(item)
        for item in session.scalars(
            select(InvoiceCollectionsReport)
            .where(InvoiceCollectionsReport.reconciliation_run_id == run_id)
            .order_by(InvoiceCollectionsReport.report_type)
        )
    ]


def decide(
    group_id: int, decision: str, body: ReviewRequest, session: Session, context: RequestContext
) -> GroupResponse:
    group = session.scalar(
        select(InvoiceCollectionsMatchGroup).where(
            InvoiceCollectionsMatchGroup.id == group_id,
            InvoiceCollectionsMatchGroup.tenant_id == context.tenant.id,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="Invoice collections group not found")
    transitions = {
        "accept": ({"suggested", "partially_matched", "needs_review", "reopened"}, "matched"),
        "reject": ({"suggested", "partially_matched", "needs_review", "reopened"}, "rejected"),
        "resolve": (
            {"partially_matched", "needs_review", "reopened", "rejected"},
            "resolved",
        ),
        "reopen": ({"matched", "resolved", "rejected"}, "reopened"),
    }
    allowed, new_status = transitions[decision]
    if group.status not in allowed:
        raise HTTPException(
            status_code=409, detail=f"Cannot {decision} a group in status {group.status}"
        )
    previous = group.status
    group.status = new_status
    group.reviewed_by_user_id = context.actor.id
    group.reviewed_at = datetime.now(UTC)
    group.notes = body.notes
    session.add(
        InvoiceCollectionsDecision(
            tenant_id=context.tenant.id,
            reconciliation_run_id=group.reconciliation_run_id,
            match_group_id=group.id,
            actor_user_id=context.actor.id,
            decision=decision,
            previous_status=previous,
            new_status=group.status,
            reason=body.reason,
            notes=body.notes,
            metadata_json={},
            decided_at=datetime.now(UTC),
        )
    )
    AuditService().record(
        session,
        context,
        event_type=f"invoice_collections_reconciliation.{decision}",
        entity_type="invoice_collections_match_group",
        entity_id=group.id,
        action=decision,
        description=f"Invoice collections match group {decision}ed",
        metadata={"previous_status": previous, "new_status": group.status},
    )
    session.commit()
    return GroupResponse.model_validate(group)


@group_router.post("/{group_id}/accept", response_model=GroupResponse)
def accept(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.review"))
    ],
) -> GroupResponse:
    return decide(group_id, "accept", body, session, context)


@group_router.post("/{group_id}/reject", response_model=GroupResponse)
def reject(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.review"))
    ],
) -> GroupResponse:
    return decide(group_id, "reject", body, session, context)


@group_router.get("/{group_id}", response_model=GroupResponse)
def group_detail(
    group_id: int,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.view"))
    ],
) -> GroupResponse:
    group = session.scalar(
        select(InvoiceCollectionsMatchGroup).where(
            InvoiceCollectionsMatchGroup.id == group_id,
            InvoiceCollectionsMatchGroup.tenant_id == context.tenant.id,
        )
    )
    if group is None:
        raise HTTPException(status_code=404, detail="Invoice collections group not found")
    return GroupResponse.model_validate(group)


@group_router.post("/{group_id}/resolve", response_model=GroupResponse)
def resolve(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.review"))
    ],
) -> GroupResponse:
    return decide(group_id, "resolve", body, session, context)


@group_router.post("/{group_id}/reopen", response_model=GroupResponse)
def reopen(
    group_id: int,
    body: ReviewRequest,
    session: Annotated[Session, Depends(get_db)],
    context: Annotated[
        RequestContext, Depends(require_permission("invoice_collections_reconciliation.review"))
    ],
) -> GroupResponse:
    return decide(group_id, "reopen", body, session, context)
