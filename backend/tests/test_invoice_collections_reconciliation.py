from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InvoiceCollectionsReconciliationRule, Tenant
from app.services.invoice_collections_reconciliation import (
    aging_bucket,
    invoice_header_total,
    invoice_line_total,
    money,
    optional_money,
)
from app.services.reconciliation_matching import bounded_exact_groups, stable_fingerprint

ANALYST = {"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": "analyst@demo.local"}
VIEWER = {"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": "viewer@demo.local"}


def test_money_and_invoice_line_formula_are_decimal_safe() -> None:
    row = {
        "quantity": "2.00",
        "unit_price": "25.50",
        "line_discount": "1.00",
        "line_tax": "2.50",
    }
    assert money("1.2") == Decimal("1.200000")
    assert invoice_line_total(row) == Decimal("52.500000")


def test_aging_boundaries_are_deterministic() -> None:
    as_of = date(2023, 12, 31)
    assert aging_bucket(as_of, date(2024, 1, 1)) == ("current", 0)
    assert aging_bucket(as_of, date(2023, 12, 1)) == ("1_30", 30)
    assert aging_bucket(as_of, date(2023, 11, 1)) == ("31_60", 60)
    assert aging_bucket(as_of, date(2023, 10, 2)) == ("61_90", 90)
    assert aging_bucket(as_of, date(2023, 10, 1)) == ("over_90", 91)


def test_invoice_header_tax_discount_and_missing_values() -> None:
    row = {"subtotal": "100.00", "tax_amount": "8.25", "discount_amount": "3.25"}
    assert invoice_header_total(row) == Decimal("105.000000")
    assert invoice_header_total({**row, "tax_amount": ""}) is None
    assert optional_money("") is None


def test_group_search_is_bounded_deterministic_and_stably_fingerprinted() -> None:
    records = [
        ("D1", Decimal("40"), date(2023, 1, 2)),
        ("D2", Decimal("60"), date(2023, 1, 3)),
        ("D3", Decimal("100"), date(2023, 2, 1)),
    ]
    groups = bounded_exact_groups(
        Decimal("100"), records, date(2023, 1, 1), 3, 3, Decimal("0.01"), 2
    )
    assert groups == [("D1", "D2")]
    payload = {"version": "1.0.0", "payment": "PAY-0001", "deposits": groups[0]}
    assert stable_fingerprint(payload) == stable_fingerprint(payload)


def test_phase_11_rules_are_seeded(db_session: Session) -> None:
    tenant = db_session.scalar(select(Tenant).where(Tenant.code == "demo_coffee_group"))
    assert tenant is not None
    count = db_session.scalar(
        select(func.count())
        .select_from(InvoiceCollectionsReconciliationRule)
        .where(
            InvoiceCollectionsReconciliationRule.tenant_id == tenant.id,
            InvoiceCollectionsReconciliationRule.version == "1.0.0",
        )
    )
    assert count == 22


def test_history_accounts_and_viewer_restrictions(client: TestClient) -> None:
    history = client.get("/api/v1/reconciliations/invoice-collections", headers=ANALYST)
    accounts = client.get("/api/v1/reconciliations/invoice-collections/accounts", headers=VIEWER)
    assert history.status_code == 200
    assert accounts.status_code == 200
    denied = client.post(
        "/api/v1/reconciliations/invoice-collections",
        headers=VIEWER,
        json={
            "bank_account_id": 1,
            "date_from": "2023-01-01",
            "date_to": "2023-12-31",
            "aging_as_of_date": "2023-12-31",
        },
    )
    assert denied.status_code == 403


def test_phase_11_required_detail_routes_are_tenant_scoped(client: TestClient) -> None:
    paths = (
        "/api/v1/reconciliations/invoice-collections/999999/invoices",
        "/api/v1/reconciliations/invoice-collections/999999/payments",
        "/api/v1/reconciliations/invoice-collections/999999/candidates",
        "/api/v1/reconciliations/invoice-collections/999999/ar-aging",
        "/api/v1/reconciliations/invoice-collections/999999/reports",
    )
    assert all(client.get(path, headers=ANALYST).status_code == 404 for path in paths)
