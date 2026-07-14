from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import DataQualityIssue, PipelineRun, SourceFile, SourceFileProfile
from app.services.csv_profiling import (
    IssueData,
    calculate_columns,
    calculate_financial_controls,
    detect_delimiter,
    detect_encoding,
    inspect_csv,
    issue_fingerprint,
)
from app.services.profile_parsing import parse_date, parse_decimal

SOURCE_CODE = "kaggle_small_business_finance"


def upload(client: TestClient, content: bytes, name: str = "profile.csv") -> int:
    response = client.post(
        "/api/v1/source-files/upload",
        files={"file": (name, content, "text/csv")},
        data={"source_system_code": SOURCE_CODE},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["source_file_id"])


def test_monetary_parser_handles_currency_commas_and_parentheses() -> None:
    assert parse_decimal("1200.50", currency=True) == parse_decimal("$1,200.50", currency=True)
    assert parse_decimal("PHP 1,200.50", currency=True) == parse_decimal("1,200.50", currency=True)
    assert parse_decimal("(1,200.50)", currency=True) == parse_decimal("-1200.50", currency=True)
    assert parse_decimal("not money", currency=True) is None


def test_date_parser_rejects_ambiguous_slash_dates() -> None:
    assert parse_date("2026-01-31").value is not None
    assert parse_date("13/01/2026").format_name == "%d/%m/%Y"
    assert parse_date("01/02/2026").ambiguous is True


def test_encoding_and_delimiter_detection() -> None:
    raw = b"\xef\xbb\xbfid;amount\n1;2\n"
    encoding, text = detect_encoding(raw, ["utf-8-sig", "utf-8"])
    assert encoding == "utf-8-sig"
    assert text is not None and detect_delimiter(text) == ";"
    plain_encoding, _ = detect_encoding(b"id,amount\n1,2\n", ["utf-8-sig", "utf-8"])
    assert plain_encoding == "utf-8"


def test_issue_fingerprint_is_deterministic() -> None:
    issue = IssueData("duplicate_rows", "data_quality", "warning", "Duplicates")
    assert issue_fingerprint(7, "1.0.0", issue) == issue_fingerprint(7, "1.0.0", issue)


def test_profile_api_persists_metrics_columns_issues_and_audit(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    content = (
        b"id,date,amount,balance,note\n"
        b"a1,2026-01-01,100.00,100.00,x\n"
        b"a2,2026-01-13,(25.00),75.00,x\n"
        b"a2,bad,$oops,80.00,x\n"
    )
    source_file_id = upload(client, content)
    before = sha256(content).hexdigest()

    response = client.post(f"/api/v1/source-files/{source_file_id}/profile")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["row_count"] == 3
    assert body["column_count"] == 5
    assert body["status"] == "completed_with_warnings"
    assert body["issue_totals"]["error"] >= 3
    columns = client.get(f"/api/v1/profiles/{body['id']}/columns")
    assert columns.status_code == 200
    assert columns.json()["total"] == 5
    issues = client.get(f"/api/v1/profiles/{body['id']}/issues?severity=error")
    assert issues.status_code == 200
    assert all(item["severity"] == "error" for item in issues.json()["items"])
    run = db_session.get(PipelineRun, body["pipeline_run_id"])
    assert run is not None and run.status == "completed_with_warnings"
    assert len(run.steps) == 9 and all(step.status == "completed" for step in run.steps)
    stored_profile = db_session.get(SourceFileProfile, body["id"])
    assert stored_profile is not None
    stored = test_settings.REGISTERED_RAW_DIRECTORY / stored_profile.source_file.stored_filename
    assert sha256(stored.read_bytes()).hexdigest() == before


def test_rerun_is_idempotent_and_keeps_attempt_audit(
    client: TestClient, db_session: Session
) -> None:
    source_file_id = upload(client, b"id,amount\na,10\na,10\n", "rerun.csv")
    first = client.post(f"/api/v1/source-files/{source_file_id}/profile")
    second = client.post(f"/api/v1/source-files/{source_file_id}/profile")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SourceFileProfile)
            .where(SourceFileProfile.source_file_id == source_file_id)
        )
        == 1
    )
    fingerprints = list(
        db_session.scalars(
            select(DataQualityIssue.issue_fingerprint).where(
                DataQualityIssue.source_file_id == source_file_id
            )
        )
    )
    assert len(fingerprints) == len(set(fingerprints))
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PipelineRun)
            .where(
                PipelineRun.source_file_id == source_file_id, PipelineRun.run_type == "csv_profile"
            )
        )
        == 2
    )


def test_missing_registered_file_records_failed_attempt(
    client: TestClient, db_session: Session, test_settings: Settings
) -> None:
    source_file_id = upload(client, b"id,amount\na,10\n", "missing-raw.csv")
    source_file = db_session.get(SourceFile, source_file_id)
    assert source_file is not None
    (test_settings.REGISTERED_RAW_DIRECTORY / source_file.stored_filename).unlink()

    response = client.post(f"/api/v1/source-files/{source_file_id}/profile")

    assert response.status_code == 422
    failed_run = db_session.scalar(
        select(PipelineRun)
        .where(PipelineRun.source_file_id == source_file_id, PipelineRun.run_type == "csv_profile")
        .order_by(PipelineRun.id.desc())
    )
    assert failed_run is not None
    db_session.refresh(failed_run)
    assert failed_run.status == "failed"
    assert any(step.status == "failed" for step in failed_run.steps)


def test_empty_header_only_bom_quoted_and_shape_issues(client: TestClient) -> None:
    empty_id = upload(client, b"", "empty.csv")
    empty = client.post(f"/api/v1/source-files/{empty_id}/profile")
    assert empty.status_code == 200 and empty.json()["status"] == "blocked"

    cases = [
        (b"id,amount\n", "header.csv"),
        (b"\xef\xbb\xbfid,amount\n1,10\n", "bom.csv"),
        (b'id,note,amount\n1,"quoted, value",10\n', "quoted.csv"),
        (b"id,amount\n1,2,3\n2\n", "shape.csv"),
        (b"description,empty\nx,\ny,\n", "missing-columns.csv"),
    ]
    for content, name in cases:
        source_id = upload(client, content, name)
        response = client.post(f"/api/v1/source-files/{source_id}/profile")
        assert response.status_code == 200, response.text

    shape_issues = client.get("/api/v1/data-quality-issues?issue_code=row_too_many_fields")
    assert shape_issues.status_code == 200 and shape_issues.json()["total"] >= 1
    missing = client.get(
        "/api/v1/data-quality-issues?issue_code=required_financial_field_not_found"
    )
    assert missing.status_code == 200 and missing.json()["total"] >= 1


def test_all_documented_profiling_fixtures_are_deterministic(test_settings: Settings) -> None:
    fixture_directory = Path(__file__).parent / "fixtures" / "profiling"
    fixture_names = {
        "clean_bank.csv",
        "duplicate_rows.csv",
        "null_heavy.csv",
        "mixed_dates.csv",
        "currency_parentheses.csv",
        "invalid_money.csv",
        "duplicate_identifiers.csv",
        "invalid_balance.csv",
        "empty.csv",
        "header_only.csv",
        "quoted.csv",
        "utf8_bom.csv",
        "missing_financial.csv",
        "all_null.csv",
        "constant_value.csv",
    }
    assert {path.name for path in fixture_directory.glob("*.csv")} == fixture_names
    analyses = {}
    tolerance = parse_decimal("0.01")
    assert tolerance is not None
    for name in fixture_names:
        analysis = inspect_csv((fixture_directory / name).read_bytes(), test_settings)
        calculate_columns(analysis, test_settings)
        calculate_financial_controls(analysis, tolerance)
        analyses[name] = analysis

    assert analyses["clean_bank.csv"].running_balance_valid is True
    assert analyses["duplicate_rows.csv"].duplicate_rows == 1
    assert analyses["currency_parentheses.csv"].monetary_total == parse_decimal("1050")
    assert analyses["invalid_balance.csv"].running_balance_valid is False
    expected_codes = {
        "mixed_dates.csv": "inconsistent_date_formats",
        "invalid_money.csv": "invalid_monetary_value",
        "duplicate_identifiers.csv": "duplicate_transaction_identifier",
        "missing_financial.csv": "required_financial_field_not_found",
        "all_null.csv": "all_null_column",
        "constant_value.csv": "constant_value_column",
    }
    for name, code in expected_codes.items():
        assert code in {issue.code for issue in analyses[name].issues}
