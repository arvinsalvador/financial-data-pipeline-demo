import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    PipelineRun,
    RawSourceRow,
    RejectedSourceRow,
    SourceFile,
    StagingBankTransaction,
    Tenant,
)

SOURCE_CODE = "kaggle_small_business_finance"


def upload_profile(client: TestClient, content: bytes) -> int:
    uploaded = client.post(
        "/api/v1/source-files/upload",
        files={"file": ("checking_account_main.csv", content, "text/csv")},
        data={"source_system_code": SOURCE_CODE},
    )
    assert uploaded.status_code == 201, uploaded.text
    source_file_id = uploaded.json()["source_file_id"]
    profiled = client.post(f"/api/v1/source-files/{source_file_id}/profile")
    assert profiled.status_code == 200, profiled.text
    return source_file_id


def test_clean_ingestion_preserves_raw_and_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    content = b"date,description,amount\n2026-01-13,Coffee,$1,234.50\n"
    # Quote the thousands-separated value so the CSV remains structurally valid.
    content = b'date,description,amount\n2026-01-13,Coffee,"$1,234.50"\n'
    source_file_id = upload_profile(client, content)

    first = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        json={"mapping_code": "checking_account_main_v1"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["records_extracted"] == 1
    assert first.json()["records_accepted"] == 1
    assert first.json()["records_rejected"] == 0
    assert first.json()["steps"][-1]["status"] == "completed"
    raw = db_session.scalar(
        select(RawSourceRow).where(RawSourceRow.source_file_id == source_file_id)
    )
    assert raw is not None
    assert raw.source_row_number == 2
    assert raw.raw_data_json["amount"] == "$1,234.50"
    staged = db_session.scalar(
        select(StagingBankTransaction).where(
            StagingBankTransaction.source_file_id == source_file_id
        )
    )
    assert staged is not None and str(staged.amount) == "1234.500000"

    second = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        json={"mapping_code": "checking_account_main_v1", "force_rerun": True},
    )
    assert second.status_code == 200
    assert second.json()["no_op"] is True
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(RawSourceRow)
            .where(RawSourceRow.source_file_id == source_file_id)
        )
        == 1
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(StagingBankTransaction)
            .where(StagingBankTransaction.source_file_id == source_file_id)
        )
        == 1
    )


def test_mixed_rows_record_multiple_deterministic_rejections(
    client: TestClient, db_session: Session
) -> None:
    source_file_id = upload_profile(
        client,
        b"date,description,amount\n2026-01-13,Valid,10.00\nbad-date,Bad,bad-money\n",
    )
    response = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        json={"mapping_code": "checking_account_main_v1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["records_extracted"] == 2
    assert response.json()["records_accepted"] == 1
    assert response.json()["records_rejected"] == 1
    rejections = list(
        db_session.scalars(
            select(RejectedSourceRow).where(RejectedSourceRow.source_file_id == source_file_id)
        ).all()
    )
    assert {item.rejection_code for item in rejections} >= {
        "invalid_date",
        "invalid_monetary_value",
    }
    assert len({item.rejection_fingerprint for item in rejections}) == len(rejections)


def test_ingestion_endpoints_are_tenant_scoped_and_viewer_cannot_execute(
    client: TestClient, db_session: Session
) -> None:
    source_file_id = upload_profile(client, b"date,description,amount\n2026-01-13,Valid,10.00\n")
    viewer = {"X-Tenant-Code": "demo_coffee_group", "X-Demo-User": "viewer@demo.local"}
    forbidden = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        headers=viewer,
        json={"mapping_code": "checking_account_main_v1"},
    )
    assert forbidden.status_code == 403
    other = db_session.scalar(
        select(Tenant).where(Tenant.code != "demo_coffee_group", Tenant.status == "active")
    )
    assert other is not None
    other_tenant = {"X-Tenant-Code": other.code, "X-Demo-User": "admin@demo.local"}
    hidden = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        headers=other_tenant,
        json={"mapping_code": "checking_account_main_v1"},
    )
    assert hidden.status_code == 404


@pytest.mark.parametrize(
    ("filename", "mapping_code", "content", "endpoint"),
    [
        (
            "checking_account_secondary.csv",
            "checking_account_secondary_v1",
            b"date,amount\n2026-02-13,-20.00\n",
            "bank-transactions",
        ),
        (
            "credit_card_account.csv",
            "credit_card_account_v1",
            b"date,merchant,amount\n2026-02-13,Cafe,(20.00)\n",
            "credit-card-transactions",
        ),
        (
            "gusto_payroll.csv",
            "gusto_payroll_v1",
            b"pay_date,employee_id,net_pay\n2026-02-13,0007,900.00\n",
            "payroll-summaries",
        ),
        (
            "gusto_payroll_bc.csv",
            "gusto_payroll_bc_v1",
            b"pay_date,employee_id,bonus,net_pay\n2026-02-13,0007,50,950\n",
            "payroll-details",
        ),
    ],
)
def test_all_source_connectors_load_their_staging_table(
    client: TestClient,
    filename: str,
    mapping_code: str,
    content: bytes,
    endpoint: str,
) -> None:
    uploaded = client.post(
        "/api/v1/source-files/upload",
        files={"file": (filename, content, "text/csv")},
        data={"source_system_code": SOURCE_CODE},
    )
    source_file_id = uploaded.json()["source_file_id"]
    assert client.post(f"/api/v1/source-files/{source_file_id}/profile").status_code == 200
    ingested = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        json={"mapping_code": mapping_code},
    )
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["records_accepted"] == 1
    staged = client.get(f"/api/v1/staging/{endpoint}?source_file_id={source_file_id}")
    assert staged.status_code == 200
    assert staged.json()["total"] == 1
    if "payroll" in endpoint:
        assert staged.json()["items"][0]["employee_source_id"] == "0007"


def test_missing_profile_and_mapping_fail_closed(client: TestClient) -> None:
    uploaded = client.post(
        "/api/v1/source-files/upload",
        files={"file": ("unknown.csv", b"date,amount\n2026-01-13,1\n", "text/csv")},
        data={"source_system_code": SOURCE_CODE},
    )
    source_file_id = uploaded.json()["source_file_id"]
    missing_profile = client.post(f"/api/v1/source-files/{source_file_id}/ingest", json={})
    assert missing_profile.status_code == 422
    assert client.post(f"/api/v1/source-files/{source_file_id}/profile").status_code == 200
    missing_mapping = client.post(f"/api/v1/source-files/{source_file_id}/ingest", json={})
    assert missing_mapping.status_code == 422


def test_checksum_mismatch_creates_failed_run(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    source_file_id = upload_profile(client, b"date,description,amount\n2026-01-13,Valid,10.00\n")
    source = db_session.get(SourceFile, source_file_id)
    assert source is not None
    physical = test_settings.REGISTERED_RAW_DIRECTORY / source.stored_filename
    physical.chmod(0o644)
    physical.write_bytes(physical.read_bytes() + b"tampered")
    response = client.post(
        f"/api/v1/source-files/{source_file_id}/ingest",
        json={"mapping_code": "checking_account_main_v1"},
    )
    assert response.status_code == 422
    run = db_session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.source_file_id == source_file_id, PipelineRun.run_type == "csv_ingestion"
        )
        .order_by(PipelineRun.id.desc())
    )
    assert run is not None and run.status == "failed"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(RawSourceRow)
            .where(RawSourceRow.source_file_id == source_file_id)
        )
        == 0
    )
