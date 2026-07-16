from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PayrollReconciliationRule, Tenant
from app.services.payroll_reconciliation import (
    BankWithdrawal,
    PayrollTotals,
    calculate_payroll_totals,
    component_sum,
    expected_settlement,
    score_payroll_bank,
)


def entry(**values: Any) -> Any:
    defaults = {
        "gross_pay": Decimal("100"),
        "employee_tax": Decimal("20"),
        "employee_deduction": Decimal("5"),
        "employer_tax": Decimal("8"),
        "employer_contribution": Decimal("4"),
        "reimbursement_amount": Decimal("2"),
        "net_pay": Decimal("77"),
    }
    return SimpleNamespace(**{**defaults, **values})


def payroll_run() -> Any:
    return SimpleNamespace(
        payroll_run_source_id="PR-100",
        pay_date=date(2023, 1, 13),
        net_pay_total=Decimal("154"),
        employer_contributions_total=Decimal("8"),
        metadata_json={},
    )


def test_internal_component_totals_are_decimal_and_complete() -> None:
    totals = calculate_payroll_totals(cast(Any, [entry(), entry()]))
    assert totals.entry_count == 2
    assert totals.gross_pay == Decimal("200.000000")
    assert totals.employee_tax == Decimal("40.000000")
    assert totals.net_pay == Decimal("154.000000")


def test_missing_component_stays_unavailable() -> None:
    values = cast(Any, [entry(employee_tax=None), entry()])
    assert component_sum(values, "employee_tax") is None
    assert calculate_payroll_totals(values).employee_tax is None


def test_settlement_models_are_explicit() -> None:
    totals = PayrollTotals(
        2,
        Decimal("200"),
        Decimal("40"),
        Decimal("10"),
        Decimal("16"),
        Decimal("8"),
        Decimal("4"),
        Decimal("154"),
    )
    assert expected_settlement(payroll_run(), totals, "net_pay_only") == Decimal("154")
    assert expected_settlement(payroll_run(), totals, "net_pay_plus_taxes") == Decimal("210")
    assert expected_settlement(payroll_run(), totals, "full_payroll_cash_requirement") == Decimal(
        "178"
    )


def test_exact_payroll_bank_score_is_transparent() -> None:
    bank = BankWithdrawal(1, date(2023, 1, 13), Decimal("154"), "PR-100", "Payroll", "a" * 64)
    result = score_payroll_bank(payroll_run(), Decimal("154"), bank, Decimal("0.01"), 3)
    assert result is not None
    confidence, reasons = result
    assert confidence == Decimal("1.000000")
    assert reasons == {
        "reference_exact": True,
        "amount_exact": True,
        "date_difference_days": 0,
        "settlement_amount": "154",
    }


def test_phase_10_rules_are_seeded(db_session: Session) -> None:
    tenant = db_session.scalar(select(Tenant).where(Tenant.code == "demo_coffee_group"))
    assert tenant is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PayrollReconciliationRule)
            .where(
                PayrollReconciliationRule.tenant_id == tenant.id,
                PayrollReconciliationRule.version == "1.0.0",
            )
        )
        == 12
    )


def test_payroll_api_history_and_accounts(client: TestClient) -> None:
    assert client.get("/api/v1/reconciliations/payroll").status_code == 200
    response = client.get("/api/v1/reconciliations/payroll/accounts")
    assert response.status_code == 200
    assert all(item["status"] for item in response.json())
