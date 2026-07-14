from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    BankLedgerReconciliationRun,
    ReconciliationAllocation,
    ReconciliationDecision,
    ReconciliationException,
    ReconciliationMatch,
    ReconciliationMatchGroup,
)

TRANSITIONS = {
    "accept": ({"suggested", "needs_review", "partially_matched", "reopened"}, "matched"),
    "reject": ({"suggested", "needs_review", "partially_matched", "reopened"}, "rejected"),
    "resolve": ({"matched", "needs_review", "partially_matched"}, "resolved"),
    "reopen": ({"matched", "resolved", "rejected"}, "reopened"),
}


def decide_group(
    session: Session,
    run: BankLedgerReconciliationRun,
    group: ReconciliationMatchGroup,
    actor_user_id: int,
    decision: str,
    reason: str,
    notes: str | None,
) -> ReconciliationDecision:
    allowed, new_status = TRANSITIONS[decision]
    if group.status not in allowed:
        raise ValueError(f"Cannot {decision} a group in {group.status} status")
    previous = group.status
    now = datetime.now(UTC)
    group.status = new_status
    group.reviewed_by_user_id = actor_user_id
    group.reviewed_at = now
    group.notes = notes
    matches = list(
        session.scalars(
            select(ReconciliationMatch).where(ReconciliationMatch.match_group_id == group.id)
        )
    )
    for match in matches:
        match.status = new_status
    if decision in {"accept", "resolve"}:
        bank_ids = {item.bank_transaction_id for item in matches}
        ledger_ids = {item.ledger_record_id for item in matches}
        conflict = session.scalar(
            select(ReconciliationAllocation.id).where(
                ReconciliationAllocation.reconciliation_run_id == run.id,
                ReconciliationAllocation.match_group_id != group.id,
                or_(
                    ReconciliationAllocation.bank_transaction_id.in_(bank_ids),
                    ReconciliationAllocation.ledger_record_id.in_(ledger_ids),
                ),
            )
        )
        if conflict is not None:
            raise ValueError("This group conflicts with an existing allocation")
        existing = {
            (item.bank_transaction_id, item.ledger_record_id)
            for item in session.scalars(
                select(ReconciliationAllocation).where(
                    ReconciliationAllocation.match_group_id == group.id
                )
            )
        }
        bank_metadata = {
            int(item["id"]): item for item in (group.metadata_json or {}).get("bank_records", [])
        }
        for match in matches:
            key = (match.bank_transaction_id, match.ledger_record_id)
            if key in existing:
                continue
            signed = Decimal(str(bank_metadata[match.bank_transaction_id]["signed_amount"]))
            session.add(
                ReconciliationAllocation(
                    tenant_id=run.tenant_id,
                    reconciliation_run_id=run.id,
                    match_group_id=group.id,
                    bank_transaction_id=match.bank_transaction_id,
                    ledger_record_id=match.ledger_record_id,
                    allocated_amount=match.matched_amount,
                    allocation_direction="inflow" if signed > 0 else "outflow",
                )
            )
    if decision == "resolve":
        for exception in session.scalars(
            select(ReconciliationException).where(
                ReconciliationException.match_group_id == group.id,
                ReconciliationException.status == "open",
            )
        ):
            exception.status = "resolved"
            exception.resolved_at = now
    record = ReconciliationDecision(
        tenant_id=run.tenant_id,
        reconciliation_run_id=run.id,
        match_group_id=group.id,
        actor_user_id=actor_user_id,
        decision=decision,
        previous_status=previous,
        new_status=new_status,
        reason=reason,
        notes=notes,
        decided_at=now,
    )
    session.add(record)
    session.flush()
    return record
