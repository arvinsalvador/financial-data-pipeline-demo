from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GeneratedRecordLink, GeneratedSourceFile, GenerationControlTotal, Tenant


def _canonical_deposit(client: TestClient) -> None:
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
    assert normalized.status_code == 200, normalized.text


def test_generation_is_registered_balanced_linked_and_idempotent(
    client: TestClient, db_session: Session, test_settings: object
) -> None:
    _canonical_deposit(client)
    generated = client.post(
        "/api/v1/generated-datasets",
        json={"random_seed": 20260714, "generation_date": "2026-07-14"},
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["status"] == "completed"
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
        json={"random_seed": 20260714, "generation_date": "2026-07-14"},
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
    tenant = Tenant(
        code="generation_isolation_tenant",
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
    finally:
        db_session.delete(tenant)
        db_session.commit()
