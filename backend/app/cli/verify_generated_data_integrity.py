import argparse
import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    GeneratedDatasetRun,
    GeneratedRecordLink,
    GeneratedSourceFile,
    GenerationControlTotal,
    SourceFile,
    Tenant,
)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Verify generated dataset integrity")
    parser.add_argument("--tenant-code", default=settings.DEFAULT_DEMO_TENANT_CODE)
    parser.add_argument("--run-id", type=int)
    args = parser.parse_args()
    failures: list[str] = []
    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.code == args.tenant_code))
        if tenant is None:
            raise SystemExit(f"Tenant not found: {args.tenant_code}")
        query = select(GeneratedDatasetRun).where(
            GeneratedDatasetRun.tenant_id == tenant.id,
            GeneratedDatasetRun.status == "completed",
        )
        if args.run_id:
            query = query.where(GeneratedDatasetRun.id == args.run_id)
        run = session.scalar(query.order_by(GeneratedDatasetRun.id.desc()))
        if run is None:
            raise SystemExit("No completed generated dataset found")
        generated_files = session.scalars(
            select(GeneratedSourceFile).where(
                GeneratedSourceFile.generated_dataset_run_id == run.id
            )
        ).all()
        if len(generated_files) != run.file_count:
            failures.append("generated file count does not match run")
        root = settings.GENERATED_DATA_DIRECTORY.resolve()
        rows: dict[str, list[dict[str, str]]] = {}
        for item in generated_files:
            try:
                relative = Path(item.relative_path).relative_to("generated")
            except ValueError:
                failures.append(f"absolute or invalid stored path: {item.relative_path}")
                continue
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                failures.append(f"missing physical file: {item.filename}")
                continue
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum != item.sha256_checksum:
                failures.append(f"checksum mismatch: {item.filename}")
            source = session.get(SourceFile, item.source_file_id)
            if (
                source is None
                or source.tenant_id != tenant.id
                or source.sha256_checksum != checksum
            ):
                failures.append(f"source registration mismatch: {item.filename}")
            rows[item.file_type] = _read(path)
        invoices = {row["invoice_id"]: row for row in rows.get("invoices", [])}
        line_totals: dict[str, Decimal] = defaultdict(Decimal)
        for line in rows.get("invoice_lines", []):
            line_totals[line["invoice_id"]] += Decimal(line["line_total"])
        for invoice_id, invoice in invoices.items():
            total = (
                Decimal(invoice["subtotal"])
                + Decimal(invoice["tax_amount"])
                - Decimal(invoice["discount_amount"])
            )
            if total != Decimal(invoice["total_amount"]) or line_totals[invoice_id] != Decimal(
                invoice["subtotal"]
            ):
                failures.append(f"invoice total mismatch: {invoice_id}")
            if Decimal(invoice["amount_paid"]) > total:
                failures.append(f"invoice overpayment: {invoice_id}")
        payment_totals = {
            row["payment_id"]: Decimal(row["payment_amount"])
            for row in rows.get("customer_payments", [])
        }
        applied: dict[str, Decimal] = defaultdict(Decimal)
        for row in rows.get("customer_payment_applications", []):
            applied[row["payment_id"]] += Decimal(row["applied_amount"])
        if payment_totals != dict(applied):
            failures.append("payment applications do not equal payments")
        journals: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
        identifiers: dict[str, set[str]] = defaultdict(set)
        primary_keys = {
            "customers": "customer_id",
            "crm_deals": "deal_id",
            "invoices": "invoice_id",
            "invoice_lines": "invoice_line_id",
            "customer_payments": "payment_id",
            "customer_payment_applications": "payment_application_id",
            "vendors": "vendor_id",
            "accounts_payable": "ap_bill_id",
            "general_ledger": "journal_line_id",
            "forecast_assumptions": "assumption_id",
        }
        for file_type, records in rows.items():
            primary = primary_keys.get(file_type)
            for row in records:
                if primary and row[primary] in identifiers[file_type]:
                    failures.append(f"duplicate identifier in {file_type}: {row[primary]}")
                if primary:
                    identifiers[file_type].add(row[primary])
        for line in rows.get("general_ledger", []):
            totals = journals[line["journal_entry_id"]]
            totals[0] += Decimal(line["debit"])
            totals[1] += Decimal(line["credit"])
        if any(debit != credit for debit, credit in journals.values()):
            failures.append("unbalanced journal entry")
        controls = session.scalars(
            select(GenerationControlTotal).where(
                GenerationControlTotal.generated_dataset_run_id == run.id
            )
        ).all()
        if not controls or any(control.status != "passed" for control in controls):
            failures.append("generation control failed")
        links = session.scalars(
            select(GeneratedRecordLink).where(
                GeneratedRecordLink.generated_dataset_run_id == run.id
            )
        ).all()
        if any(link.tenant_id != tenant.id for link in links):
            failures.append("cross-tenant generated record link")
        manifest_path = (
            root / "manifests" / tenant.code / f"run_{run.id:08d}" / "generation_manifest.json"
        )
        if not manifest_path.is_file():
            failures.append("generation manifest missing")
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = {item["filename"]: item["sha256"] for item in manifest["generated_files"]}
            actual = {item.filename: item.sha256_checksum for item in generated_files}
            if expected != actual:
                failures.append("manifest file inventory mismatch")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        raise SystemExit(1)
    print(
        f"generated data integrity verified: run={run.id} files={len(generated_files)} "
        f"journals={len(journals)} controls={len(controls)} links={len(links)}"
    )


if __name__ == "__main__":
    main()
