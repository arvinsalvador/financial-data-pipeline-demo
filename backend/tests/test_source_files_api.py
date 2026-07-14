from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import PipelineRun, PipelineRunStep, SourceFile

SOURCE_CODE = "kaggle_small_business_finance"
CSV_BYTES = b"date,description,amount\n2026-01-01,Opening balance,100.00\n"


def upload_csv(
    client: TestClient,
    *,
    filename: str = "checking_account_main.csv",
    content: bytes = CSV_BYTES,
    source_code: str = SOURCE_CODE,
    mime_type: str = "text/csv",
) -> object:
    return client.post(
        "/api/v1/source-files/upload",
        files={"file": (filename, content, mime_type)},
        data={"source_system_code": source_code},
    )


def test_successful_csv_upload_creates_file_and_audit_records(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    response = upload_csv(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "registered"
    assert body["original_filename"] == "checking_account_main.csv"
    assert body["file_size_bytes"] == len(CSV_BYTES)

    source_file = db_session.get(SourceFile, body["source_file_id"])
    run = db_session.get(PipelineRun, body["pipeline_run_id"])
    step = db_session.scalar(
        select(PipelineRunStep).where(PipelineRunStep.pipeline_run_id == body["pipeline_run_id"])
    )
    assert source_file is not None
    assert source_file.relative_path.startswith("raw/registered/")
    assert not Path(source_file.relative_path).is_absolute()
    assert run is not None and run.status == "registered"
    assert run.source_file_id == source_file.id
    assert step is not None and step.status == "registered"

    registered = test_settings.REGISTERED_RAW_DIRECTORY / source_file.stored_filename
    assert registered.read_bytes() == CSV_BYTES


def test_unsupported_extension_is_audited(client: TestClient, db_session: Session) -> None:
    response = upload_csv(client, filename="ledger.txt")

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_extension"
    run = db_session.get(PipelineRun, response.json()["pipeline_run_id"])
    assert run is not None and run.status == "failed"


def test_oversized_file_is_rejected(client: TestClient) -> None:
    response = upload_csv(client, content=b"x" * 129)

    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"


def test_missing_source_system_is_rejected(client: TestClient) -> None:
    response = upload_csv(client, source_code="missing")

    assert response.status_code == 404
    assert response.json()["code"] == "missing_source_system"


def test_invalid_mime_type_is_rejected(client: TestClient) -> None:
    response = upload_csv(client, mime_type="application/pdf")

    assert response.status_code == 415
    assert response.json()["code"] == "invalid_mime_type"


def test_path_traversal_filename_is_rejected(client: TestClient) -> None:
    response = upload_csv(client, filename="../escape.csv")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_filename"


def test_duplicate_upload_creates_no_second_source_file(
    client: TestClient, db_session: Session
) -> None:
    source_file_count = db_session.scalar(select(func.count()).select_from(SourceFile)) or 0
    pipeline_run_count = db_session.scalar(select(func.count()).select_from(PipelineRun)) or 0
    first = upload_csv(client)
    duplicate = upload_csv(client, filename="same_bytes_different_name.csv")

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["existing_source_file_id"] == first.json()["source_file_id"]
    assert db_session.scalar(select(func.count()).select_from(SourceFile)) == source_file_count + 1
    assert (
        db_session.scalar(select(func.count()).select_from(PipelineRun)) == pipeline_run_count + 2
    )


def test_source_system_listing(client: TestClient) -> None:
    response = client.get("/api/v1/source-systems")

    assert response.status_code == 200
    assert response.json()["items"][0]["code"] == SOURCE_CODE


def test_source_file_listing_and_detail_do_not_expose_absolute_paths(client: TestClient) -> None:
    uploaded = upload_csv(client, content=CSV_BYTES + b"listing")
    source_file_id = uploaded.json()["source_file_id"]

    listing = client.get("/api/v1/source-files")
    detail = client.get(f"/api/v1/source-files/{source_file_id}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == source_file_id
    assert detail.status_code == 200
    assert detail.json()["relative_path"].startswith("raw/registered/")
    assert "/data/" not in detail.text


def test_pipeline_run_listing_and_detail(client: TestClient) -> None:
    uploaded = upload_csv(client, content=CSV_BYTES + b"runs")
    run_id = uploaded.json()["pipeline_run_id"]

    listing = client.get("/api/v1/pipeline-runs")
    detail = client.get(f"/api/v1/pipeline-runs/{run_id}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == run_id
    assert detail.status_code == 200
    assert detail.json()["steps"][0]["step_name"] == "receive_and_register"


def test_source_file_pagination(client: TestClient) -> None:
    starting_total = client.get("/api/v1/source-files?page_size=1").json()["total"]
    upload_csv(client, content=CSV_BYTES + b"page-one")
    upload_csv(client, content=CSV_BYTES + b"page-two")

    first_page = client.get("/api/v1/source-files?page=1&page_size=1")
    second_page = client.get("/api/v1/source-files?page=2&page_size=1")

    assert first_page.status_code == 200
    assert first_page.json()["total"] == starting_total + 2
    assert len(first_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]
