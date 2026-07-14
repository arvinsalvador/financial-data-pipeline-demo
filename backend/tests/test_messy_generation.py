from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DataMutation, ExpectedException, MessyDatasetRun, MessySourceFile
from app.services.messy.mutation_services import MutationDispatcher
from app.services.messy.types import CsvDocument, CsvRow, PlannedMutation
from tests.test_generation import _canonical_deposit


def _clean_run(client: TestClient) -> dict[str, object]:
    _canonical_deposit(client)
    response = client.post(
        "/api/v1/generated-datasets",
        json={"random_seed": 20260714, "generation_date": "2026-07-14"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_seeded_scenarios_are_stable_and_ordered(client: TestClient) -> None:
    response = client.get("/api/v1/defect-scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert [item["code"] for item in scenarios] == [
        "hostile_messy_v1",
        "light_messy_v1",
        "standard_messy_v1",
    ]
    standard = next(item for item in scenarios if item["code"] == "standard_messy_v1")
    detail = client.get(f"/api/v1/defect-scenarios/{standard['id']}").json()
    orders = [rule["rule_order"] for rule in detail["rules"]]
    assert orders == sorted(orders)
    assert detail["enabled_rule_count"] == 30


def test_messy_generation_is_separate_auditable_and_idempotent(
    client: TestClient, db_session: Session, test_settings: object
) -> None:
    clean = _clean_run(client)
    clean_files = client.get(f"/api/v1/generated-datasets/{clean['id']}/files").json()["items"]
    clean_checksums = {item["id"]: item["sha256_checksum"] for item in clean_files}
    request = {
        "clean_generated_dataset_run_id": clean["id"],
        "scenario_code": "standard_messy_v1",
        "random_seed": 20260714,
    }
    generated = client.post("/api/v1/messy-datasets", json=request)
    assert generated.status_code == 200, generated.text
    run = generated.json()
    assert run["status"] == "completed_with_warnings"
    assert run["messy_file_count"] == run["clean_file_count"] == 10
    assert run["applied_defect_count"] == run["expected_exception_count"]
    assert run["skipped_defect_count"] > 0
    assert run["failed_defect_count"] == 0
    assert len(run["pipeline_steps"]) == 20
    assert len(run["artifacts"]) == 5

    files = client.get(f"/api/v1/messy-datasets/{run['id']}/files").json()
    mutations = client.get(f"/api/v1/messy-datasets/{run['id']}/mutations").json()
    expected = client.get(f"/api/v1/messy-datasets/{run['id']}/expected-exceptions").json()
    controls = client.get(f"/api/v1/messy-datasets/{run['id']}/control-totals").json()
    assert files["total"] == 10
    assert mutations["total"] == run["requested_defect_count"]
    assert expected["total"] == run["expected_exception_count"]
    assert controls["items"] and {item["status"] for item in controls["items"]} == {"matched"}
    assert all(not Path(item["relative_path"]).is_absolute() for item in files["items"])
    assert all(item["clean_generated_source_file_id"] in clean_checksums for item in files["items"])
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(MessySourceFile)
            .where(MessySourceFile.messy_dataset_run_id == run["id"])
        )
        == 10
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(DataMutation)
            .where(
                DataMutation.messy_dataset_run_id == run["id"],
                DataMutation.mutation_status == "applied",
            )
        )
        == run["applied_defect_count"]
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ExpectedException)
            .where(ExpectedException.messy_dataset_run_id == run["id"])
        )
        == run["expected_exception_count"]
    )
    after = client.get(f"/api/v1/generated-datasets/{clean['id']}/files").json()["items"]
    assert {item["id"]: item["sha256_checksum"] for item in after} == clean_checksums

    repeated = client.post("/api/v1/messy-datasets", json={**request, "force_rerun": True})
    assert repeated.status_code == 200
    assert repeated.json()["id"] == run["id"]
    assert repeated.json()["no_op"] is True
    assert repeated.json()["output_fingerprint"] == run["output_fingerprint"]

    filtered = client.get(
        f"/api/v1/messy-datasets/{run['id']}/mutations?defect_type=overpayment"
    ).json()
    assert filtered["total"] == 1
    severe = client.get(
        f"/api/v1/messy-datasets/{run['id']}/expected-exceptions?severity=critical"
    ).json()
    assert severe["total"] > 0


def test_viewer_can_inspect_but_cannot_generate_or_list_scenarios(client: TestClient) -> None:
    client.headers["X-Demo-User"] = "viewer@demo.local"
    assert client.get("/api/v1/messy-datasets").status_code == 200
    assert client.get("/api/v1/defect-scenarios").status_code == 403
    response = client.post(
        "/api/v1/messy-datasets",
        json={"clean_generated_dataset_run_id": 1, "scenario_code": "light_messy_v1"},
    )
    assert response.status_code == 403


def test_dispatcher_applies_row_cell_and_schema_mutations() -> None:
    cases = [
        ("exact_duplicate_row", None, 2),
        ("missing_transaction_identifier", "journal_line_id", 1),
        ("inconsistent_date_format", "entry_date", 1),
        ("invalid_account_code", "account_code", 1),
        ("unexpected_extra_column", None, 1),
    ]
    for defect, column, expected_rows in cases:
        document = CsvDocument(
            "general_ledger",
            ["journal_line_id", "entry_date", "account_code"],
            [CsvRow(["JL-1", "2026-01-01", "1000"], 2)],
        )
        plan = PlannedMutation(
            1,
            f"rule_{defect}",
            1,
            defect,
            "general_ledger",
            "general_ledger.csv",
            2,
            "JL-1",
            column,
            None,
            None,
            "error",
            (defect.upper(),),
            configuration={"format": "%m/%d/%Y"},
        )
        result = MutationDispatcher().apply({"general_ledger": document}, plan)
        assert result[0].status == "applied"
        assert len(document.rows) == expected_rows


def test_messy_history_is_tenant_scoped(client: TestClient, db_session: Session) -> None:
    other = db_session.scalar(select(MessyDatasetRun).where(MessyDatasetRun.tenant_id != 1))
    response = client.get("/api/v1/messy-datasets")
    assert response.status_code == 200
    if other is not None:
        assert other.id not in {item["id"] for item in response.json()["items"]}
