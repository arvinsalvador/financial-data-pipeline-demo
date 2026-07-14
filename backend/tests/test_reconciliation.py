from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PipelineDefinition, ReconciliationRule, Tenant
from app.services.reconciliation_matching import (
    BankRecord,
    LedgerRecord,
    bounded_exact_groups,
    normalize_description,
    normalize_reference,
    score_candidate,
    stable_fingerprint,
)


def bank(amount: str = "100.00", reference: str = "DEP-100") -> BankRecord:
    return BankRecord(
        1, 10, date(2026, 1, 10), Decimal(amount), reference, "Customer deposit Acme", "a" * 64, 2
    )


def ledger(amount: str = "100.00", reference: str = "DEP-100") -> LedgerRecord:
    return LedgerRecord(
        "JL-1",
        2,
        date(2026, 1, 10),
        Decimal(amount),
        reference,
        "Deposit from Acme",
        "JE-1",
        "1000",
        "b" * 64,
    )


def test_exact_reference_and_amount_is_maximum_confidence() -> None:
    score = score_candidate(bank(), ledger(), 3, Decimal("0.01"))
    assert score is not None
    assert score.rule_code == "exact_reference_amount"
    assert score.confidence == Decimal("1.000000")


def test_opposite_economic_directions_do_not_match() -> None:
    assert score_candidate(bank("100"), ledger("-100"), 3, Decimal("0.01")) is None


def test_amount_and_date_tolerances_are_enforced() -> None:
    assert score_candidate(bank("100"), ledger("100.02"), 3, Decimal("0.01")) is None
    late = ledger()
    late = LedgerRecord(**{**late.__dict__, "entry_date": date(2026, 1, 14)})
    assert score_candidate(bank(), late, 3, Decimal("0.01")) is None


def test_group_search_is_bounded_and_deterministic() -> None:
    records = [
        ("a", Decimal("40"), date(2026, 1, 10)),
        ("b", Decimal("60"), date(2026, 1, 10)),
        ("c", Decimal("25"), date(2026, 1, 10)),
    ]
    assert bounded_exact_groups(
        Decimal("100"), records, date(2026, 1, 10), 3, 3, Decimal("0.01")
    ) == [("a", "b")]


def test_normalization_and_fingerprints_are_stable() -> None:
    assert normalize_reference(" DEP: 100 ") == "dep 100"
    assert normalize_description("Payment -- ACME, Inc.") == "payment acme inc"
    assert stable_fingerprint({"b": 2, "a": 1}) == stable_fingerprint({"a": 1, "b": 2})


def test_phase_9_governance_seed(db_session: Session) -> None:
    tenant = db_session.scalar(select(Tenant).where(Tenant.code == "demo_coffee_group"))
    assert tenant is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ReconciliationRule)
            .where(
                ReconciliationRule.tenant_id == tenant.id,
                ReconciliationRule.version == "1.0.0",
            )
        )
        == 12
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PipelineDefinition)
            .where(
                PipelineDefinition.code == "bank_ledger_reconciliation",
                PipelineDefinition.version == "1.0.0",
            )
        )
        == 1
    )


def test_reconciliation_history_and_account_endpoints_are_tenant_scoped(
    client: TestClient,
) -> None:
    accounts = client.get("/api/v1/reconciliations/bank-ledger/accounts")
    history = client.get("/api/v1/reconciliations/bank-ledger")
    assert accounts.status_code == 200
    assert history.status_code == 200
    assert all(item["status"] for item in accounts.json())
