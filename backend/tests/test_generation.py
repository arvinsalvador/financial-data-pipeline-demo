from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    GeneratedRecordLink,
    GeneratedSourceFile,
    GenerationControlTotal,
    Tenant,
)


def _canonical_deposit(client: TestClient) -> int:
    uploaded = client.post(
        "/api/v1/source-files/upload",
        files={
            "file": (
                "checking_account_main.csv",
                b"date,description,amount,currency\n2026-01-13,Customer deposit,125.50,USD\n",
                "text/csv",
            )
        },
        data={"source_system_code": "kaggle_small_business_finance"},
    )
    assert uploaded.status_code == 201, uploaded.text
    source_file_id = uploaded.json()["source_file_id"]
    assert client.post(f"/api/v1/source-files/{source_file_id}/profile").status_code == 200
    ingestion = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        json={"mapping_code": "checking_account_main_v1"},
    )
    assert ingestion.status_code == 200, ingestion.text
    normalized = client.post(
        f"/api/v1/ingestions/{ingestion.json()['id']}/normalize",
        json={"mapping_code": "bank_transaction_main_v1"},
    )
    return int(normalized.json()["id"])
    assert normalized.status_code == 200, normalized.text


def test_generation_is_registered_balanced_linked_and_idempotent(
    client: TestClient, db_session: Session, test_settings: object
) -> None:
    normalization_run_id = _canonical_deposit(client)
    eligibility = client.get("/api/v1/generated-datasets/eligible-inputs")
    assert eligibility.status_code == 200, eligibility.text
    candidate = next(
        item
        for item in eligibility.json()["items"]
        if item["normalization_run_id"] == normalization_run_id
    )
    assert candidate["eligible"] is True
    assert candidate["canonical_counts"]["bank_transactions"] >= 1
    generated = client.post(
        "/api/v1/generated-datasets",
        json={
            "normalization_run_id": normalization_run_id,
            "random_seed": 20260714,
            "generation_date": "2026-07-14",
        },
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["status"] == "completed"
    assert body["normalization_run_id"] == normalization_run_id
    assert body["file_count"] == 10
    files = client.get(f"/api/v1/generated-datasets/{body['id']}/files")
    assert files.status_code == 200 and files.json()["total"] == 10
    assert all(not Path(item["relative_path"]).is_absolute() for item in files.json()["items"])
    ledger_file = next(
        item for item in files.json()["items"] if item["file_type"] == "general_ledger"
    )
    ledger = client.get(f"/api/v1/generated-source-files/{ledger_file['id']}/records")
    assert ledger.status_code == 200
    assert ledger.json()["items"][0]["journal_line_id"].startswith("JL-")
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(GeneratedSourceFile)
            .where(GeneratedSourceFile.generated_dataset_run_id == body["id"])
        )
        == 10
    )
    controls = db_session.scalars(
        select(GenerationControlTotal).where(
            GenerationControlTotal.generated_dataset_run_id == body["id"]
        )
    ).all()
    assert controls and {control.status for control in controls} == {"passed"}
    assert db_session.scalar(
        select(func.count())
        .select_from(GeneratedRecordLink)
        .where(GeneratedRecordLink.generated_dataset_run_id == body["id"])
    )
    repeated = client.post(
        "/api/v1/generated-datasets",
        json={
            "normalization_run_id": normalization_run_id,
            "random_seed": 20260714,
            "generation_date": "2026-07-14",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == body["id"]
    assert repeated.json()["no_op"] is True


def test_viewer_cannot_execute_generation(client: TestClient) -> None:
    client.headers["X-Demo-User"] = "viewer@demo.local"
    response = client.post(
        "/api/v1/generated-datasets",
        json={"random_seed": 20260714, "generation_date": "2026-07-14"},
    )
    assert response.status_code == 403


def test_generated_history_is_tenant_isolated(client: TestClient, db_session: Session) -> None:
    normalization_run_id = _canonical_deposit(client)
    tenant = Tenant(
        code=f"generation_isolation_tenant_{normalization_run_id}",
        name="Generation Isolation Tenant",
        display_name="Generation Isolation Tenant",
        status="active",
        default_currency="USD",
        timezone="UTC",
        fiscal_year_start_month=1,
    )
    db_session.add(tenant)
    db_session.commit()
    try:
        client.headers["X-Tenant-Code"] = tenant.code
        client.headers["X-Demo-User"] = "admin@demo.local"
        response = client.get("/api/v1/generated-datasets")
        assert response.status_code == 200
        assert response.json()["items"] == []
        hidden_input = client.post(
            "/api/v1/generated-datasets",
            json={"normalization_run_id": normalization_run_id},
        )
        assert hidden_input.status_code == 422
    finally:
        db_session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant.id))
        db_session.delete(tenant)
        db_session.commit()
