from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BankAccount,
    BankTransaction,
    CanonicalRecordLineage,
    Currency,
    FinancialTransaction,
    NormalizationMapping,
    TransactionCategory,
)

SOURCE_CODE = "kaggle_small_business_finance"


def ingest(client: TestClient, filename: str, content: bytes, ingestion_mapping: str) -> int:
    uploaded = client.post(
        "/api/v1/source-files/upload",
        files={"file": (filename, content, "text/csv")},
        data={"source_system_code": SOURCE_CODE},
    )
    assert uploaded.status_code == 201, uploaded.text
    source_file_id = uploaded.json()["source_file_id"]
    assert client.post(f"/api/v1/source-files/{source_file_id}/profile").status_code == 200
    ingested = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        json={"mapping_code": ingestion_mapping},
    )
    assert ingested.status_code == 200, ingested.text
    return int(ingested.json()["id"])


def test_canonical_seed_is_present(db_session: Session) -> None:
    assert set(db_session.scalars(select(Currency.code)).all()) >= {"USD", "PHP"}
    assert db_session.scalar(select(func.count()).select_from(BankAccount)) >= 2
    assert db_session.scalar(select(func.count()).select_from(TransactionCategory)) >= 10
    assert db_session.scalar(select(func.count()).select_from(NormalizationMapping)) >= 5


def test_bank_normalization_creates_transaction_lineage_controls_and_no_op(
    client: TestClient, db_session: Session
) -> None:
    ingestion_id = ingest(
        client,
        "checking_account_main.csv",
        b"date,description,amount,currency\n2026-01-13,Customer deposit,125.50,USD\n",
        "checking_account_main_v1",
    )
    normalized = client.post(
        f"/api/v1/ingestions/{ingestion_id}/normalize",
        json={"mapping_code": "bank_transaction_main_v1"},
    )
    assert normalized.status_code == 200, normalized.text
    body = normalized.json()
    assert body["status"] == "completed"
    assert body["staging_count"] == body["canonical_count"] == 1
    transaction = db_session.scalar(
        select(FinancialTransaction).where(FinancialTransaction.normalization_run_id == body["id"])
    )
    assert transaction is not None and str(transaction.amount) == "125.500000"
    bank = db_session.scalar(
        select(BankTransaction).where(BankTransaction.financial_transaction_id == transaction.id)
    )
    assert bank is not None and bank.transaction_direction == "inflow"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(CanonicalRecordLineage)
            .where(CanonicalRecordLineage.canonical_entity_id == bank.id)
        )
        == 1
    )
    controls = client.get(f"/api/v1/normalizations/{body['id']}/control-totals")
    assert controls.status_code == 200
    assert {item["status"] for item in controls.json()} == {"matched"}
    repeated = client.post(
        f"/api/v1/ingestions/{ingestion_id}/normalize",
        json={"mapping_code": "bank_transaction_main_v1", "force_rerun": True},
    )
    assert repeated.status_code == 200 and repeated.json()["no_op"] is True
    assert db_session.scalar(select(func.count()).select_from(BankTransaction)) == 1


def test_credit_card_purchase_uses_positive_liability_convention(client: TestClient) -> None:
    ingestion_id = ingest(
        client,
        "credit_card_account.csv",
        b"date,merchant,description,amount\n2026-01-13,Cafe,Coffee,-20.00\n",
        "credit_card_account_v1",
    )
    normalized = client.post(
        f"/api/v1/ingestions/{ingestion_id}/normalize",
        json={"mapping_code": "credit_card_transaction_v1"},
    )
    assert normalized.status_code == 200, normalized.text
    records = client.get("/api/v1/canonical/credit-card-transactions")
    assert records.status_code == 200
    assert records.json()["items"][0]["transaction_direction"] == "purchase"
    assert records.json()["items"][0]["purchase_amount"] == "20.000000"


def test_payroll_detail_normalizes_employee_and_preserves_leading_zero(client: TestClient) -> None:
    ingestion_id = ingest(
        client,
        "gusto_payroll_bc.csv",
        b"pay_date,employee_id,gross_pay,net_pay\n2026-01-13,0007,1000,800\n",
        "gusto_payroll_bc_v1",
    )
    normalized = client.post(
        f"/api/v1/ingestions/{ingestion_id}/normalize",
        json={"mapping_code": "payroll_detail_v1"},
    )
    assert normalized.status_code == 200, normalized.text
    entries = client.get("/api/v1/canonical/payroll-entries")
    employees = client.get("/api/v1/canonical/employees")
    assert entries.json()["total"] == 1
    assert employees.json()["items"][0]["employee_source_id"] == "0007"


def test_viewer_cannot_normalize_and_cross_tenant_records_are_hidden(
    client: TestClient, db_session: Session
) -> None:
    ingestion_id = ingest(
        client,
        "checking_account_secondary.csv",
        b"date,description,amount\n2026-01-13,Payroll,-50\n",
        "checking_account_secondary_v1",
    )
    viewer = {"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": "viewer@demo.local"}
    denied = client.post(f"/api/v1/ingestions/{ingestion_id}/normalize", headers=viewer, json={})
    assert denied.status_code == 403
    from app.models import Tenant

    other = db_session.scalar(
        select(Tenant).where(Tenant.code != "demo_coffee_group", Tenant.status == "active")
    )
    assert other is not None
    hidden = client.post(
        f"/api/v1/ingestions/{ingestion_id}/normalize",
        headers={"X-Tenant-Code": other.code, "X-Demo-User": "admin@demo.local"},
        json={},
    )
    assert hidden.status_code == 404


def test_negative_bank_amount_is_outflow_and_invalid_currency_is_exception(
    client: TestClient,
) -> None:
    outflow_ingestion = ingest(
        client,
        "checking_account_main.csv",
        b"date,description,amount\n2026-02-13,Service fee,-12.50\n",
        "checking_account_main_v1",
    )
    normalized = client.post(
        f"/api/v1/ingestions/{outflow_ingestion}/normalize",
        json={"mapping_code": "bank_transaction_main_v1"},
    )
    assert normalized.status_code == 200
    bank = client.get("/api/v1/canonical/bank-transactions").json()["items"][0]
    assert bank["transaction_direction"] == "outflow"

    invalid_ingestion = ingest(
        client,
        "checking_account_secondary.csv",
        b"date,description,amount,currency\n2026-02-14,Payroll,-50,XXX\n",
        "checking_account_secondary_v1",
    )
    invalid = client.post(
        f"/api/v1/ingestions/{invalid_ingestion}/normalize",
        json={"mapping_code": "bank_transaction_secondary_v1"},
    )
    assert invalid.status_code == 200
    assert invalid.json()["status"] == "completed_with_exceptions"
    assert invalid.json()["canonical_count"] == 0
    assert invalid.json()["exception_count"] == 1


def test_payroll_detail_precedence_prevents_summary_double_count(client: TestClient) -> None:
    summary_ingestion = ingest(
        client,
        "gusto_payroll.csv",
        b"pay_date,employee_id,gross_pay,net_pay\n2026-03-13,0009,1000,800\n",
        "gusto_payroll_v1",
    )
    summary = client.post(
        f"/api/v1/ingestions/{summary_ingestion}/normalize",
        json={"mapping_code": "payroll_summary_v1"},
    )
    assert summary.status_code == 200
    detail_ingestion = ingest(
        client,
        "gusto_payroll_bc.csv",
        b"pay_date,employee_id,gross_pay,bonus,net_pay\n2026-03-13,0009,1000,100,800\n",
        "gusto_payroll_bc_v1",
    )
    detail = client.post(
        f"/api/v1/ingestions/{detail_ingestion}/normalize",
        json={"mapping_code": "payroll_detail_v1"},
    )
    assert detail.status_code == 200, detail.text
    entries = client.get("/api/v1/canonical/payroll-entries").json()
    assert entries["total"] == 1
    assert entries["items"][0]["bonus_pay"] == "100.000000"
    lineage = client.get(
        f"/api/v1/canonical/payroll_entry/{entries['items'][0]['id']}/lineage"
    ).json()
    assert lineage["total"] == 2
