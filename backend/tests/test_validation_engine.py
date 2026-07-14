from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant, ValidationIssue, ValidationReport, ValidationRunResult
from app.services.validation_engine import (
    ValidationContext,
    ValidationDocument,
    ValidationRuleRegistry,
)
from tests.test_generation import _canonical_deposit


def _document(file_type: str, headers: list[str], rows: list[list[str]]) -> ValidationDocument:
    return ValidationDocument(file_type, f"{file_type}.csv", None, headers, rows)


def test_modular_rules_detect_schema_fields_dates_money_duplicates_and_relationships(
    db_session: Session,
) -> None:
    tenant = db_session.scalar(select(Tenant).where(Tenant.code == "demo_coffee_group"))
    assert tenant is not None
    documents = {
        "customers": _document(
            "customers",
            ["customer_id", "customer_name", "status", "status"],
            [["", "Acme", "active", "active"], ["CUST-1", "Acme", "active", "active"]],
        ),
        "invoices": _document(
            "invoices",
            [
                "invoice_id",
                "customer_id",
                "invoice_date",
                "due_date",
                "currency",
                "total_amount",
            ],
            [
                ["INV-1", "MISSING", "bad-date", "2020-01-01", "usd", "not-money"],
                ["INV-1", "MISSING", "2026-01-02", "2026-01-01", "USD", "10.00"],
            ],
        ),
        "general_ledger": _document(
            "general_ledger",
            [
                "journal_entry_id",
                "journal_line_id",
                "entry_date",
                "account_code",
                "currency",
                "debit",
                "credit",
            ],
            [["JE-1", "JL-1", "2026-01-01", "1000", "USD", "10", "0"]],
        ),
    }
    context = ValidationContext(db_session, tenant.id, "tenant", None, documents, {})
    registry = ValidationRuleRegistry()
    expected = {
        "schema_expected_columns": "DUPLICATE_COLUMN",
        "required_fields": "MISSING_REQUIRED_FIELD",
        "identifier_presence_format": "BLANK_IDENTIFIER",
        "date_values": "INVALID_DATE",
        "monetary_values": "INVALID_DECIMAL",
        "duplicate_identifiers": "DUPLICATE_IDENTIFIER",
        "relationships": "ORPHAN_RELATIONSHIP",
        "gl_balanced": "UNBALANCED_JOURNAL",
        "invoice_date_order": "DUE_BEFORE_INVOICE",
    }
    for code, issue_code in expected.items():
        plugin = registry.get(code)
        assert plugin is not None
        assert issue_code in {finding.code for finding in plugin.execute(context).findings}


def _messy_fixture(client: TestClient) -> dict[str, object]:
    _canonical_deposit(client)
    clean = client.post(
        "/api/v1/generated-datasets",
        json={"random_seed": 20260714, "generation_date": "2026-07-14"},
    )
    assert clean.status_code == 200, clean.text
    messy = client.post(
        "/api/v1/messy-datasets",
        json={
            "clean_generated_dataset_run_id": clean.json()["id"],
            "scenario_code": "light_messy_v1",
            "random_seed": 20260714,
        },
    )
    assert messy.status_code == 200, messy.text
    return messy.json()


def test_validation_run_reports_filters_controls_and_idempotency(
    client: TestClient, db_session: Session
) -> None:
    messy = _messy_fixture(client)
    request = {"target_type": "messy_dataset", "target_id": messy["id"]}
    response = client.post("/api/v1/validation/run", json=request)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["validation_version"] == "1.0.0"
    assert run["total_rules"] == 26
    assert run["records_evaluated"] > 0
    assert run["duration_ms"] < 10_000
    assert run["status"] in {"completed", "completed_with_issues"}
    assert (
        run["information_count"] + run["warning_count"] + run["error_count"] + run["critical_count"]
        == run["total_issues"]
    )
    summary = client.get(f"/api/v1/validation/summary?run_id={run['id']}")
    assert summary.status_code == 200
    assert summary.json()["issue_count"] == run["total_issues"]
    reports = client.get(f"/api/v1/validation/reports?run_id={run['id']}").json()
    assert reports["total"] == 7
    assert {item["report_type"] for item in reports["items"]} == {
        "validation_summary",
        "validation_report",
        "validation_statistics",
        "validation_by_severity",
        "validation_by_rule",
        "validation_by_file",
        "validation_by_entity",
    }
    results = client.get(f"/api/v1/validation/runs/{run['id']}/results").json()
    assert results["total"] == 26
    critical = client.get(f"/api/v1/validation/issues?run_id={run['id']}&severity=critical").json()
    assert critical["total"] == run["critical_count"]
    assert db_session.scalar(
        select(ValidationRunResult).where(ValidationRunResult.validation_run_id == run["id"])
    )
    assert db_session.scalar(
        select(ValidationReport).where(ValidationReport.validation_run_id == run["id"])
    )
    if run["total_issues"]:
        issue = db_session.scalar(
            select(ValidationIssue).where(ValidationIssue.validation_run_id == run["id"])
        )
        assert issue is not None
        detail = client.get(f"/api/v1/validation/issues/{issue.id}")
        assert detail.status_code == 200
    repeated = client.post("/api/v1/validation/run", json={**request, "force_rerun": True})
    assert repeated.status_code == 200
    assert repeated.json()["id"] == run["id"]
    assert repeated.json()["no_op"] is True


def test_validation_permissions_and_tenant_scope(client: TestClient) -> None:
    client.headers["X-Demo-User"] = "viewer@demo.local"
    assert client.get("/api/v1/validation/runs").status_code == 200
    assert client.get("/api/v1/validation/rules").status_code == 200
    assert client.post("/api/v1/validation/run", json={"target_type": "tenant"}).status_code == 403
    client.headers["X-Tenant-Code"] = "unknown_validation_tenant"
    assert client.get("/api/v1/validation/runs").status_code in {403, 404}
