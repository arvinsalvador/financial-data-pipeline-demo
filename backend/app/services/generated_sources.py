import csv
import hashlib
import io
import json
import random
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    BankAccount,
    BankTransaction,
    CreditAccount,
    CreditCardTransaction,
    FinancialTransaction,
    GeneratedDatasetRun,
    GeneratedRecordLink,
    GeneratedSourceFile,
    GenerationControlTotal,
    GenerationException,
    PayrollRun,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    SourceFile,
    SourceSystem,
    Tenant,
)

MONEY = Decimal("0.01")
GENERATION_RULESET = "phase6_clean_business_rules_v4"
FILE_ORDER = (
    "customers",
    "crm_deals",
    "invoices",
    "invoice_lines",
    "customer_payments",
    "customer_payment_applications",
    "vendors",
    "accounts_payable",
    "general_ledger",
    "forecast_assumptions",
)
PIPELINE_STEPS = (
    "validate_tenant_and_permissions",
    "load_canonical_history",
    "validate_generation_prerequisites",
    "generate_customers",
    "generate_crm_deals",
    "generate_invoices_and_lines",
    "generate_customer_payments",
    "generate_vendors",
    "generate_accounts_payable",
    "generate_general_ledger",
    "generate_forecast_assumptions",
    "write_generated_files",
    "register_generated_source_files",
    "create_generated_record_links",
    "calculate_generation_controls",
    "validate_generated_invariants",
    "create_manifest_and_reports",
    "finalize_generation",
)
HEADERS: dict[str, tuple[str, ...]] = {
    "customers": (
        "customer_id",
        "customer_code",
        "customer_name",
        "customer_type",
        "email",
        "phone",
        "billing_address",
        "city",
        "state",
        "postal_code",
        "country",
        "payment_terms_days",
        "credit_limit",
        "status",
        "created_date",
        "source_relationship_key",
    ),
    "crm_deals": (
        "deal_id",
        "customer_id",
        "deal_name",
        "pipeline_stage",
        "created_date",
        "expected_close_date",
        "closed_date",
        "deal_value",
        "probability",
        "owner_name",
        "source_channel",
        "status",
        "related_invoice_id",
        "source_relationship_key",
    ),
    "invoices": (
        "invoice_id",
        "invoice_number",
        "customer_id",
        "deal_id",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "tax_amount",
        "discount_amount",
        "total_amount",
        "amount_paid",
        "balance_due",
        "status",
        "source_relationship_key",
    ),
    "invoice_lines": (
        "invoice_line_id",
        "invoice_id",
        "line_number",
        "product_service_code",
        "description",
        "quantity",
        "unit_price",
        "line_discount",
        "line_tax",
        "line_total",
        "revenue_category",
        "source_relationship_key",
    ),
    "customer_payments": (
        "payment_id",
        "payment_reference",
        "customer_id",
        "payment_date",
        "currency",
        "payment_amount",
        "payment_method",
        "deposit_reference",
        "canonical_bank_transaction_id",
        "status",
        "unapplied_amount",
        "source_relationship_key",
    ),
    "customer_payment_applications": (
        "payment_application_id",
        "payment_id",
        "invoice_id",
        "applied_amount",
        "application_date",
        "source_relationship_key",
    ),
    "vendors": (
        "vendor_id",
        "vendor_code",
        "vendor_name",
        "vendor_type",
        "email",
        "phone",
        "payment_terms_days",
        "currency",
        "status",
        "source_relationship_key",
    ),
    "accounts_payable": (
        "ap_bill_id",
        "bill_number",
        "vendor_id",
        "bill_date",
        "due_date",
        "currency",
        "subtotal",
        "tax_amount",
        "total_amount",
        "amount_paid",
        "balance_due",
        "status",
        "canonical_payment_transaction_id",
        "source_relationship_key",
    ),
    "general_ledger": (
        "gl_batch_id",
        "journal_entry_id",
        "journal_line_id",
        "entry_date",
        "posting_date",
        "account_code",
        "account_name",
        "debit",
        "credit",
        "currency",
        "description",
        "reference_number",
        "source_type",
        "source_record_id",
        "canonical_transaction_id",
        "payroll_run_id",
        "customer_id",
        "vendor_id",
        "invoice_id",
        "ap_bill_id",
        "source_relationship_key",
    ),
    "forecast_assumptions": (
        "assumption_id",
        "assumption_code",
        "assumption_name",
        "assumption_category",
        "effective_start_date",
        "effective_end_date",
        "frequency",
        "amount",
        "percentage",
        "currency",
        "scenario",
        "source_basis",
        "source_record_id",
        "is_manual",
        "notes",
        "source_relationship_key",
    ),
}


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationResult:
    run: GeneratedDatasetRun
    no_op: bool


def _money(value: Decimal | int | None) -> Decimal:
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)


def _amount(value: Decimal | int | None) -> str:
    return f"{_money(value):.2f}"


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()


def _csv_bytes(file_type: str, rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=HEADERS[file_type], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class GeneratedSourceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(
        self,
        session: Session,
        tenant: Tenant,
        random_seed: int | None = None,
        generation_date: date | None = None,
        force_rerun: bool = False,
    ) -> GenerationResult:
        seed = random_seed if random_seed is not None else self.settings.GENERATION_RANDOM_SEED
        generated_on = generation_date or date(2026, 7, 14)
        bank, cards, payroll = self._history(session, tenant.id)
        fingerprint = self._fingerprint(tenant.id, seed, generated_on, bank, cards, payroll)
        existing = session.scalar(
            select(GeneratedDatasetRun).where(
                GeneratedDatasetRun.tenant_id == tenant.id,
                GeneratedDatasetRun.input_fingerprint == fingerprint,
                GeneratedDatasetRun.generator_version == self.settings.GENERATOR_VERSION,
                GeneratedDatasetRun.random_seed == seed,
                GeneratedDatasetRun.status == "completed",
            )
        )
        if existing is not None:
            if force_rerun:
                self._verify_physical_files(session, existing)
            return GenerationResult(existing, True)
        if not bank and not cards and not payroll:
            session.add(
                GenerationException(
                    tenant_id=tenant.id,
                    input_fingerprint=fingerprint,
                    exception_code="canonical_history_missing",
                    severity="critical",
                    message="Canonical bank, card, or payroll history is required.",
                    details_json={"tenant_code": tenant.code},
                )
            )
            session.commit()
            raise GenerationError("Canonical bank, card, or payroll history is required")

        now = datetime.now(UTC)
        definition = session.scalar(
            select(PipelineDefinition).where(
                PipelineDefinition.code == "demo_source_generation",
                PipelineDefinition.version == self.settings.GENERATOR_VERSION,
            )
        )
        source_system = session.scalar(
            select(SourceSystem).where(
                SourceSystem.tenant_id == tenant.id,
                SourceSystem.code == "generated_demo_business",
                SourceSystem.is_active.is_(True),
            )
        )
        if definition is None or source_system is None:
            raise GenerationError("Run the Phase 6 bootstrap before generation")
        pipeline = PipelineRun(
            tenant_id=tenant.id,
            pipeline_definition_id=definition.id,
            run_type="demo_source_generation",
            status="running",
            started_at=now,
            metadata_json={
                "generator_version": self.settings.GENERATOR_VERSION,
                "random_seed": seed,
                "input_fingerprint": fingerprint,
            },
        )
        session.add(pipeline)
        session.flush()
        dates = [row[0].transaction_date for row in bank + cards] + [
            row.pay_date for row in payroll
        ]
        run = GeneratedDatasetRun(
            tenant_id=tenant.id,
            pipeline_run_id=pipeline.id,
            input_fingerprint=fingerprint,
            generator_version=self.settings.GENERATOR_VERSION,
            random_seed=seed,
            generation_date=generated_on,
            base_date_start=min(dates) if dates else None,
            base_date_end=max(dates) if dates else None,
            source_bank_transaction_count=len(bank),
            source_credit_card_transaction_count=len(cards),
            source_payroll_run_count=len(payroll),
            status="running",
            metadata_json={"rounding_policy": "ROUND_HALF_UP to 0.01", "clean_data": True},
            started_at=now,
        )
        session.add(run)
        session.flush()
        try:
            rows, links = self._build(seed, generated_on, bank, cards, payroll)
            files = {name: _csv_bytes(name, rows[name]) for name in FILE_ORDER}
            self._validate(rows)
            controls = self._controls(rows, bank, payroll)
            self._write_and_register(session, tenant, source_system, run, files, rows)
            session.add_all(
                GeneratedRecordLink(
                    tenant_id=tenant.id,
                    generated_dataset_run_id=run.id,
                    generated_file_type=link[0],
                    generated_record_key=link[1],
                    relationship_type=link[2],
                    related_entity_type=link[3],
                    related_entity_id=str(link[4]),
                )
                for link in links
            )
            session.add_all(
                GenerationControlTotal(
                    tenant_id=tenant.id,
                    generated_dataset_run_id=run.id,
                    control_name=name,
                    expected_value=expected,
                    actual_value=actual,
                    difference=actual - expected,
                    status="passed" if actual == expected else "failed",
                    details_json={"tolerance": "0.00"},
                )
                for name, expected, actual in controls
            )
            self._artifacts(session, tenant, run, rows, files, links, controls)
            completed = datetime.now(UTC)
            run.status = pipeline.status = "completed"
            run.completed_at = pipeline.completed_at = completed
            run.file_count = len(files)
            run.record_count = sum(len(item) for item in rows.values())
            run.generated_customer_count = len(rows["customers"])
            run.generated_vendor_count = len(rows["vendors"])
            run.generated_deal_count = len(rows["crm_deals"])
            run.generated_invoice_count = len(rows["invoices"])
            run.generated_payment_count = len(rows["customer_payments"])
            run.generated_ap_bill_count = len(rows["accounts_payable"])
            run.generated_gl_entry_count = len(
                {r["journal_entry_id"] for r in rows["general_ledger"]}
            )
            pipeline.records_extracted = len(bank) + len(cards) + len(payroll)
            pipeline.records_accepted = run.record_count
            for order, name in enumerate(PIPELINE_STEPS, 1):
                session.add(
                    PipelineRunStep(
                        pipeline_run_id=pipeline.id,
                        step_name=name,
                        step_order=order,
                        status="completed",
                        started_at=now,
                        completed_at=completed,
                        metadata_json={"generated_record_count": run.record_count},
                    )
                )
            session.commit()
            session.refresh(run)
            return GenerationResult(run, False)
        except Exception as error:
            session.rollback()
            failed_pipeline = session.get(PipelineRun, pipeline.id)
            failed_run = session.get(GeneratedDatasetRun, run.id)
            if failed_pipeline is not None:
                failed_pipeline.status, failed_pipeline.error_message = "failed", str(error)
                failed_pipeline.completed_at = datetime.now(UTC)
            if failed_run is not None:
                failed_run.status, failed_run.completed_at = "failed", datetime.now(UTC)
            session.commit()
            raise

    def _history(
        self, session: Session, tenant_id: int
    ) -> tuple[list[Any], list[Any], list[PayrollRun]]:
        bank = list(
            session.execute(
                select(FinancialTransaction, BankTransaction, BankAccount)
                .join(
                    BankTransaction,
                    BankTransaction.financial_transaction_id == FinancialTransaction.id,
                )
                .join(BankAccount, BankAccount.id == BankTransaction.bank_account_id)
                .where(FinancialTransaction.tenant_id == tenant_id)
                .order_by(FinancialTransaction.transaction_date, FinancialTransaction.id)
            ).all()
        )
        cards = list(
            session.execute(
                select(FinancialTransaction, CreditCardTransaction, CreditAccount)
                .join(
                    CreditCardTransaction,
                    CreditCardTransaction.financial_transaction_id == FinancialTransaction.id,
                )
                .join(CreditAccount, CreditAccount.id == CreditCardTransaction.credit_account_id)
                .where(FinancialTransaction.tenant_id == tenant_id)
                .order_by(FinancialTransaction.transaction_date, FinancialTransaction.id)
            ).all()
        )
        payroll = list(
            session.scalars(
                select(PayrollRun)
                .where(PayrollRun.tenant_id == tenant_id)
                .order_by(PayrollRun.pay_date, PayrollRun.id)
            ).all()
        )
        return bank, cards, payroll

    def _fingerprint(
        self,
        tenant_id: int,
        seed: int,
        generated_on: date,
        bank: list[Any],
        cards: list[Any],
        payroll: list[PayrollRun],
    ) -> str:
        payload = {
            "tenant_id": tenant_id,
            "generator_version": self.settings.GENERATOR_VERSION,
            "seed": seed,
            "generation_date": generated_on.isoformat(),
            "generation_ruleset": GENERATION_RULESET,
            "bank": [row[0].canonical_hash for row in bank],
            "cards": [row[0].canonical_hash for row in cards],
            "payroll": [row.canonical_hash for row in payroll],
        }
        return _sha(_canonical_json(payload))

    def _build(
        self,
        seed: int,
        generated_on: date,
        bank: list[Any],
        cards: list[Any],
        payroll: list[PayrollRun],
    ) -> tuple[dict[str, list[dict[str, Any]]], list[tuple[str, str, str, str, int]]]:
        rows: dict[str, list[dict[str, Any]]] = {name: [] for name in FILE_ORDER}
        links: list[tuple[str, str, str, str, int]] = []
        rng = random.Random(seed)
        deposits = [
            row
            for row in bank
            if not self._is_bank_outflow(row)
            and abs(_money(row[0].amount))
            >= Decimal(str(self.settings.GENERATION_MIN_CUSTOMER_DEPOSIT))
        ]
        withdrawals = [row for row in bank if self._is_bank_outflow(row)]
        customer_count = max(self.settings.GENERATED_CUSTOMER_COUNT, len(deposits))
        names = [
            "Harbor Office Catering",
            "Northstar Hospitality",
            "Juniper Event Studio",
            "Lantern Market Collective",
            "Maple & Stone Hotels",
            "Bluebird Workplace Services",
            "Cedar Grove Retail",
            "Summit Subscription Club",
            "Orchid Conference Group",
            "Copper Table Restaurants",
            "Riverbend Community Center",
            "Atlas Creative Works",
        ]
        rng.shuffle(names)
        types = (
            "corporate_catering",
            "wholesale",
            "event_client",
            "retail_partner",
            "subscription",
        )
        for i in range(customer_count):
            cid = f"CUST-{i + 1:04d}"
            name = names[i % len(names)] + (f" {i // len(names) + 1}" if i >= len(names) else "")
            rows["customers"].append(
                {
                    "customer_id": cid,
                    "customer_code": cid,
                    "customer_name": name,
                    "customer_type": types[i % len(types)],
                    "email": f"billing+{cid.lower()}@example.invalid",
                    "phone": f"+1-202-555-{1000 + i:04d}",
                    "billing_address": f"{100 + i} Fiction Avenue",
                    "city": "Demo City",
                    "state": "NY",
                    "postal_code": f"100{i % 10}0",
                    "country": "US",
                    "payment_terms_days": "30",
                    "credit_limit": _amount(Decimal("25000") + i * 1000),
                    "status": "active",
                    "created_date": (generated_on - timedelta(days=365 + i)).isoformat(),
                    "source_relationship_key": f"customer:{cid}",
                }
            )

        invoice_index = 0
        for i, item in enumerate(deposits):
            transaction, bank_detail, _account = item
            invoice_index += 1
            year = transaction.transaction_date.year
            customer = f"CUST-{i % customer_count + 1:04d}"
            deal = f"DEAL-{year}-{invoice_index:04d}"
            invoice = f"INV-{year}-{invoice_index:04d}"
            payment = f"PAY-{year}-{invoice_index:04d}"
            value = _money(transaction.amount)
            rows["crm_deals"].append(
                self._deal(
                    deal,
                    customer,
                    invoice,
                    transaction.transaction_date,
                    value,
                    "closed_won",
                    invoice_index,
                )
            )
            rows["invoices"].append(
                self._invoice(
                    invoice, deal, customer, transaction.transaction_date, value, value, "paid"
                )
            )
            rows["invoice_lines"].append(self._invoice_line(invoice, value))
            rows["customer_payments"].append(
                {
                    "payment_id": payment,
                    "payment_reference": payment,
                    "customer_id": customer,
                    "payment_date": transaction.transaction_date.isoformat(),
                    "currency": "USD",
                    "payment_amount": _amount(value),
                    "payment_method": "ach",
                    "deposit_reference": transaction.reference_number or f"BANK-{transaction.id}",
                    "canonical_bank_transaction_id": str(bank_detail.id),
                    "status": "applied",
                    "unapplied_amount": _amount(0),
                    "source_relationship_key": f"payment:{payment}",
                }
            )
            rows["customer_payment_applications"].append(
                {
                    "payment_application_id": f"PAPP-{year}-{invoice_index:04d}",
                    "payment_id": payment,
                    "invoice_id": invoice,
                    "applied_amount": _amount(value),
                    "application_date": transaction.transaction_date.isoformat(),
                    "source_relationship_key": f"payment_application:{payment}:{invoice}",
                }
            )
            links.extend(
                (
                    (
                        "customer_payments",
                        payment,
                        "settles_as",
                        "bank_transaction",
                        bank_detail.id,
                    ),
                    ("invoices", invoice, "collected_by", "bank_transaction", bank_detail.id),
                )
            )

        open_count = min(3, customer_count)
        for i in range(open_count):
            invoice_index += 1
            customer = f"CUST-{(len(deposits) + i) % customer_count + 1:04d}"
            year = generated_on.year
            deal = f"DEAL-{year}-{invoice_index:04d}"
            invoice = f"INV-{year}-{invoice_index:04d}"
            value = _money(Decimal("1500") + Decimal(i * 375))
            invoice_date = generated_on - timedelta(days=50 - i * 18)
            stage = "closed_won" if i < 2 else "proposal"
            related = invoice if stage == "closed_won" else ""
            rows["crm_deals"].append(
                self._deal(deal, customer, related, invoice_date, value, stage, invoice_index)
            )
            if related:
                status = "overdue" if invoice_date + timedelta(days=30) < generated_on else "issued"
                rows["invoices"].append(
                    self._invoice(invoice, deal, customer, invoice_date, value, Decimal(0), status)
                )
                rows["invoice_lines"].append(self._invoice_line(invoice, value))
        lost_id = f"DEAL-{generated_on.year}-{invoice_index + 1:04d}"
        rows["crm_deals"].append(
            self._deal(
                lost_id,
                "CUST-0001",
                "",
                generated_on - timedelta(days=20),
                Decimal("900"),
                "closed_lost",
                invoice_index + 1,
            )
        )

        vendor_sources = [
            ("bank", item)
            for item in withdrawals
            if "payroll" not in (item[0].description or "").lower()
        ]
        vendor_sources += [("card", item) for item in cards if _money(item[0].amount) != 0]
        vendor_names = [
            "Ember Coffee Imports",
            "Fieldstone Foods",
            "Parcel & Cup Packaging",
            "Beacon Utilities",
            "Cloud Till Software",
            "Fiction Plaza Properties",
            "Brightline Maintenance",
            "Civic Ledger Advisors",
        ]
        rng.shuffle(vendor_names)
        for i, (kind, item) in enumerate(vendor_sources):
            transaction, detail, _account = item
            vid = f"VEND-{i + 1:04d}"
            bill = f"AP-{transaction.transaction_date.year}-{i + 1:04d}"
            value = abs(_money(transaction.amount))
            rows["vendors"].append(
                {
                    "vendor_id": vid,
                    "vendor_code": vid,
                    "vendor_name": vendor_names[i % len(vendor_names)]
                    + (f" {i // len(vendor_names) + 1}" if i >= len(vendor_names) else ""),
                    "vendor_type": (
                        "coffee_supplier",
                        "food_supplier",
                        "packaging_supplier",
                        "utilities",
                        "software",
                        "maintenance",
                    )[i % 6],
                    "email": f"accounts+{vid.lower()}@example.invalid",
                    "phone": f"+1-202-555-{3000 + i:04d}",
                    "payment_terms_days": "30",
                    "currency": "USD",
                    "status": "active",
                    "source_relationship_key": f"vendor:{vid}",
                }
            )
            canonical_id = detail.id
            rows["accounts_payable"].append(
                {
                    "ap_bill_id": bill,
                    "bill_number": bill,
                    "vendor_id": vid,
                    "bill_date": transaction.transaction_date.isoformat(),
                    "due_date": (transaction.transaction_date + timedelta(days=30)).isoformat(),
                    "currency": "USD",
                    "subtotal": _amount(value),
                    "tax_amount": _amount(0),
                    "total_amount": _amount(value),
                    "amount_paid": _amount(value),
                    "balance_due": _amount(0),
                    "status": "paid",
                    "canonical_payment_transaction_id": str(canonical_id),
                    "source_relationship_key": f"ap_bill:{bill}",
                }
            )
            links.append(("accounts_payable", bill, "paid_by", f"{kind}_transaction", canonical_id))

        self._ledger(rows, deposits, vendor_sources, withdrawals, payroll)
        for line in rows["general_ledger"]:
            if line["payroll_run_id"]:
                links.append(
                    (
                        "general_ledger",
                        line["journal_line_id"],
                        "derived_from",
                        "payroll_run",
                        int(line["payroll_run_id"]),
                    )
                )
            if line["canonical_transaction_id"]:
                entity_type = (
                    "credit_card_transaction"
                    if line["source_type"] == "credit_card_purchase"
                    else "bank_transaction"
                )
                links.append(
                    (
                        "general_ledger",
                        line["journal_line_id"],
                        "derived_from",
                        entity_type,
                        int(line["canonical_transaction_id"]),
                    )
                )
        self._assumptions(rows, generated_on, deposits, withdrawals, payroll)
        for values in rows.values():
            values.sort(key=lambda value: tuple(str(value.get(key, "")) for key in value))
        return rows, links

    @staticmethod
    def _is_bank_outflow(row: Any) -> bool:
        transaction, bank_transaction, _account = row
        if bank_transaction.transaction_direction == "outflow" or _money(transaction.amount) < 0:
            return True
        description = (transaction.description or "").casefold()
        return "payment" in description or "payroll funding" in description

    def _deal(
        self,
        deal: str,
        customer: str,
        invoice: str,
        created: date,
        value: Decimal,
        stage: str,
        index: int,
    ) -> dict[str, Any]:
        closed = created + timedelta(days=7) if stage.startswith("closed_") else None
        return {
            "deal_id": deal,
            "customer_id": customer,
            "deal_name": f"Coffee services opportunity {index:04d}",
            "pipeline_stage": stage,
            "created_date": created.isoformat(),
            "expected_close_date": (created + timedelta(days=14)).isoformat(),
            "closed_date": closed.isoformat() if closed else "",
            "deal_value": _amount(value),
            "probability": "100"
            if stage == "closed_won"
            else ("0" if stage == "closed_lost" else "60"),
            "owner_name": "Demo Revenue Team",
            "source_channel": "synthetic_referral",
            "status": "closed" if stage.startswith("closed_") else "open",
            "related_invoice_id": invoice,
            "source_relationship_key": f"deal:{deal}",
        }

    def _invoice(
        self,
        invoice: str,
        deal: str,
        customer: str,
        issued: date,
        total: Decimal,
        paid: Decimal,
        status: str,
    ) -> dict[str, Any]:
        return {
            "invoice_id": invoice,
            "invoice_number": invoice,
            "customer_id": customer,
            "deal_id": deal,
            "invoice_date": issued.isoformat(),
            "due_date": (issued + timedelta(days=30)).isoformat(),
            "currency": "USD",
            "subtotal": _amount(total),
            "tax_amount": _amount(0),
            "discount_amount": _amount(0),
            "total_amount": _amount(total),
            "amount_paid": _amount(paid),
            "balance_due": _amount(total - paid),
            "status": status,
            "source_relationship_key": f"invoice:{invoice}",
        }

    def _invoice_line(self, invoice: str, value: Decimal) -> dict[str, Any]:
        return {
            "invoice_line_id": f"{invoice}-L01",
            "invoice_id": invoice,
            "line_number": "1",
            "product_service_code": "COFFEE-SERVICE",
            "description": "Synthetic coffee and hospitality services",
            "quantity": "1.00",
            "unit_price": _amount(value),
            "line_discount": _amount(0),
            "line_tax": _amount(0),
            "line_total": _amount(value),
            "revenue_category": "service_revenue",
            "source_relationship_key": f"invoice_line:{invoice}:1",
        }

    def _gl_pair(
        self,
        rows: dict[str, list[dict[str, Any]]],
        index: int,
        posted: date,
        debit_account: tuple[str, str],
        credit_account: tuple[str, str],
        value: Decimal,
        source_type: str,
        source_id: str,
        canonical_id: str = "",
        payroll_id: str = "",
        customer: str = "",
        vendor: str = "",
        invoice: str = "",
        bill: str = "",
    ) -> None:
        journal = f"JE-{posted.year}-{index:06d}"
        common = {
            "gl_batch_id": f"GLB-{posted.year}",
            "journal_entry_id": journal,
            "entry_date": posted.isoformat(),
            "posting_date": posted.isoformat(),
            "currency": "USD",
            "description": f"Synthetic {source_type.replace('_', ' ')}",
            "reference_number": source_id,
            "source_type": source_type,
            "source_record_id": source_id,
            "canonical_transaction_id": canonical_id,
            "payroll_run_id": payroll_id,
            "customer_id": customer,
            "vendor_id": vendor,
            "invoice_id": invoice,
            "ap_bill_id": bill,
        }
        for line, account, debit, credit in (
            (1, debit_account, value, 0),
            (2, credit_account, 0, value),
        ):
            rows["general_ledger"].append(
                {
                    **common,
                    "journal_line_id": f"JL-{posted.year}-{index:06d}-{line:02d}",
                    "account_code": account[0],
                    "account_name": account[1],
                    "debit": _amount(debit),
                    "credit": _amount(credit),
                    "source_relationship_key": f"gl:{journal}:{line}",
                }
            )

    def _ledger(
        self,
        rows: dict[str, list[dict[str, Any]]],
        deposits: list[Any],
        vendor_sources: list[Any],
        withdrawals: list[Any],
        payroll: list[PayrollRun],
    ) -> None:
        index = 0
        for i, item in enumerate(deposits):
            transaction, detail, _ = item
            value, customer = (
                _money(transaction.amount),
                f"CUST-{i % len(rows['customers']) + 1:04d}",
            )
            invoice = rows["customer_payments"][i]["payment_id"].replace("PAY-", "INV-")
            index += 1
            self._gl_pair(
                rows,
                index,
                transaction.transaction_date,
                ("1100", "Accounts Receivable"),
                ("4000", "Sales Revenue"),
                value,
                "customer_invoice",
                invoice,
                customer=customer,
                invoice=invoice,
            )
            index += 1
            self._gl_pair(
                rows,
                index,
                transaction.transaction_date,
                ("1000", "Cash - Main Operating Account"),
                ("1100", "Accounts Receivable"),
                value,
                "customer_payment",
                rows["customer_payments"][i]["payment_id"],
                str(detail.id),
                customer=customer,
                invoice=invoice,
            )
        paid_lookup = {
            row["canonical_payment_transaction_id"]: row for row in rows["accounts_payable"]
        }
        for transaction, detail, account in withdrawals:
            if "payroll" in (transaction.description or "").lower():
                index += 1
                self._gl_pair(
                    rows,
                    index,
                    transaction.transaction_date,
                    ("2020", "Payroll Deductions Payable"),
                    (
                        "1010" if account.account_type == "payroll" else "1000",
                        "Cash - Payroll Account"
                        if account.account_type == "payroll"
                        else "Cash - Main Operating Account",
                    ),
                    abs(_money(transaction.amount)),
                    "payroll_payment",
                    str(detail.id),
                    str(detail.id),
                )
        for kind, item in vendor_sources:
            transaction, detail, account = item
            ap = paid_lookup[str(detail.id)]
            value, vendor, bill = abs(_money(transaction.amount)), ap["vendor_id"], ap["ap_bill_id"]
            if kind == "bank":
                index += 1
                self._gl_pair(
                    rows,
                    index,
                    transaction.transaction_date,
                    ("5100", "General Operating Expense"),
                    ("2010", "Accounts Payable"),
                    value,
                    "ap_bill",
                    bill,
                    vendor=vendor,
                    bill=bill,
                )
                index += 1
                cash_code = "1010" if account.account_type == "payroll" else "1000"
                cash_name = (
                    "Cash - Payroll Account"
                    if cash_code == "1010"
                    else "Cash - Main Operating Account"
                )
                self._gl_pair(
                    rows,
                    index,
                    transaction.transaction_date,
                    ("2010", "Accounts Payable"),
                    (cash_code, cash_name),
                    value,
                    "ap_payment",
                    bill,
                    str(detail.id),
                    vendor=vendor,
                    bill=bill,
                )
            else:
                index += 1
                self._gl_pair(
                    rows,
                    index,
                    transaction.transaction_date,
                    ("5100", "General Operating Expense"),
                    ("2000", "Credit Card Payable"),
                    value,
                    "credit_card_purchase",
                    bill,
                    str(detail.id),
                    vendor=vendor,
                    bill=bill,
                )
        for invoice_row in rows["invoices"]:
            if invoice_row["amount_paid"] == "0.00":
                index += 1
                self._gl_pair(
                    rows,
                    index,
                    date.fromisoformat(invoice_row["invoice_date"]),
                    ("1100", "Accounts Receivable"),
                    ("4000", "Sales Revenue"),
                    Decimal(invoice_row["total_amount"]),
                    "customer_invoice",
                    invoice_row["invoice_id"],
                    customer=invoice_row["customer_id"],
                    invoice=invoice_row["invoice_id"],
                )
        for run in payroll:
            value = _money(run.gross_pay_total) + _money(run.employer_contributions_total)
            index += 1
            self._gl_pair(
                rows,
                index,
                run.pay_date,
                ("5000", "Payroll Expense"),
                ("2020", "Payroll Deductions Payable"),
                value,
                "payroll_run",
                run.payroll_run_source_id,
                payroll_id=str(run.id),
            )

    def _assumptions(
        self,
        rows: dict[str, list[dict[str, Any]]],
        generated_on: date,
        deposits: list[Any],
        withdrawals: list[Any],
        payroll: list[PayrollRun],
    ) -> None:
        values = (
            (
                "COLLECTIONS",
                "Expected customer collections",
                "expected_collection",
                sum((_money(x[0].amount) for x in deposits), Decimal(0)) / max(len(deposits), 1),
                "canonical_bank_deposits",
            ),
            (
                "VENDOR",
                "Expected vendor payments",
                "vendor_payment",
                sum((abs(_money(x[0].amount)) for x in withdrawals), Decimal(0))
                / max(len(withdrawals), 1),
                "canonical_bank_withdrawals",
            ),
            (
                "PAYROLL",
                "Expected biweekly payroll",
                "payroll",
                sum((_money(x.net_pay_total) for x in payroll), Decimal(0)) / max(len(payroll), 1),
                "canonical_payroll_runs",
            ),
        )
        multipliers = (
            ("base", Decimal("1.00")),
            ("conservative", Decimal("0.90")),
            ("optimistic", Decimal("1.10")),
        )
        index = 0
        for code, name, category, amount, basis in values:
            for scenario, multiplier in multipliers:
                index += 1
                aid = f"ASM-{index:04d}"
                rows["forecast_assumptions"].append(
                    {
                        "assumption_id": aid,
                        "assumption_code": f"{code}_{scenario.upper()}",
                        "assumption_name": f"{name} - {scenario}",
                        "assumption_category": category,
                        "effective_start_date": generated_on.isoformat(),
                        "effective_end_date": (generated_on + timedelta(days=91)).isoformat(),
                        "frequency": "biweekly" if category == "payroll" else "weekly",
                        "amount": _amount(amount * multiplier),
                        "percentage": "",
                        "currency": "USD",
                        "scenario": scenario,
                        "source_basis": basis,
                        "source_record_id": "aggregate",
                        "is_manual": "false",
                        "notes": "Clean deterministic assumption; no forecast calculated.",
                        "source_relationship_key": f"assumption:{aid}",
                    }
                )

    def _validate(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        line_totals: dict[str, Decimal] = {}
        for line in rows["invoice_lines"]:
            line_totals[line["invoice_id"]] = line_totals.get(
                line["invoice_id"], Decimal(0)
            ) + Decimal(line["line_total"])
        for invoice in rows["invoices"]:
            total = (
                Decimal(invoice["subtotal"])
                + Decimal(invoice["tax_amount"])
                - Decimal(invoice["discount_amount"])
            )
            if total != Decimal(invoice["total_amount"]) or line_totals[
                invoice["invoice_id"]
            ] != Decimal(invoice["subtotal"]):
                raise GenerationError(f"Invoice invariant failed: {invoice['invoice_id']}")
            if Decimal(invoice["amount_paid"]) > total:
                raise GenerationError(f"Invoice overpayment: {invoice['invoice_id']}")
        journals: dict[str, list[Decimal]] = {}
        for line in rows["general_ledger"]:
            totals = journals.setdefault(line["journal_entry_id"], [Decimal(0), Decimal(0)])
            totals[0] += Decimal(line["debit"])
            totals[1] += Decimal(line["credit"])
        if any(debit != credit for debit, credit in journals.values()):
            raise GenerationError("General ledger contains an unbalanced journal entry")

    def _controls(
        self, rows: dict[str, list[dict[str, Any]]], bank: list[Any], payroll: list[PayrollRun]
    ) -> list[tuple[str, Decimal, Decimal]]:
        invoice_total = sum((Decimal(row["total_amount"]) for row in rows["invoices"]), Decimal(0))
        line_total = sum((Decimal(row["line_total"]) for row in rows["invoice_lines"]), Decimal(0))
        payment_total = sum(
            (Decimal(row["payment_amount"]) for row in rows["customer_payments"]), Decimal(0)
        )
        application_total = sum(
            (Decimal(row["applied_amount"]) for row in rows["customer_payment_applications"]),
            Decimal(0),
        )
        debit = sum((Decimal(row["debit"]) for row in rows["general_ledger"]), Decimal(0))
        credit = sum((Decimal(row["credit"]) for row in rows["general_ledger"]), Decimal(0))
        linked_inflow = sum(
            (abs(_money(item[0].amount)) for item in bank if not self._is_bank_outflow(item)),
            Decimal(0),
        )
        payroll_expected = sum(
            (
                _money(item.gross_pay_total) + _money(item.employer_contributions_total)
                for item in payroll
            ),
            Decimal(0),
        )
        payroll_actual = sum(
            (
                Decimal(row["debit"])
                for row in rows["general_ledger"]
                if row["source_type"] == "payroll_run"
            ),
            Decimal(0),
        )
        ap_total = sum(
            (Decimal(row["total_amount"]) for row in rows["accounts_payable"]), Decimal(0)
        )
        ap_settlement = sum(
            (
                Decimal(row["amount_paid"]) + Decimal(row["balance_due"])
                for row in rows["accounts_payable"]
            ),
            Decimal(0),
        )
        linked_outflow = sum(
            (abs(_money(item[0].amount)) for item in bank if self._is_bank_outflow(item)),
            Decimal(0),
        )
        cash_credits = sum(
            (
                Decimal(row["credit"])
                for row in rows["general_ledger"]
                if row["source_type"] in {"ap_payment", "payroll_payment"}
            ),
            Decimal(0),
        )
        return [
            ("invoice_total_equals_lines", invoice_total, line_total),
            ("payments_equal_applications", payment_total, application_total),
            ("ap_total_equals_paid_plus_balance", ap_total, ap_settlement),
            ("general_ledger_balances", debit, credit),
            ("linked_cash_inflows", linked_inflow, payment_total),
            ("linked_cash_outflows", linked_outflow, cash_credits),
            ("payroll_journal_total", payroll_expected, payroll_actual),
        ]

    def _write_and_register(
        self,
        session: Session,
        tenant: Tenant,
        source_system: SourceSystem,
        run: GeneratedDatasetRun,
        files: dict[str, bytes],
        rows: dict[str, list[dict[str, Any]]],
    ) -> None:
        root = self.settings.GENERATED_DATA_DIRECTORY.resolve()
        output = (root / "clean" / tenant.code / f"run_{run.id:08d}").resolve()
        if root not in output.parents:
            raise GenerationError("Generated output directory is outside the configured root")
        output.mkdir(parents=True, exist_ok=False)
        registered_root = self.settings.REGISTERED_RAW_DIRECTORY.resolve()
        registered_root.mkdir(parents=True, exist_ok=True)
        fixed_time = datetime.combine(run.generation_date, datetime.min.time(), tzinfo=UTC)
        for file_type in FILE_ORDER:
            filename, content = f"{file_type}.csv", files[file_type]
            path = output / filename
            path.write_bytes(content)
            checksum = _sha(content)
            source_file = session.scalar(
                select(SourceFile).where(
                    SourceFile.tenant_id == tenant.id, SourceFile.sha256_checksum == checksum
                )
            )
            if source_file is None:
                stored = f"{tenant.code}_generated_{checksum[:16]}_{filename}"
                registered_path = registered_root / stored
                if not registered_path.exists():
                    shutil.copyfile(path, registered_path)
                source_file = SourceFile(
                    tenant_id=tenant.id,
                    source_system_id=source_system.id,
                    original_filename=filename,
                    stored_filename=stored,
                    relative_path=f"raw/registered/{stored}",
                    file_extension=".csv",
                    mime_type="text/csv",
                    file_size_bytes=len(content),
                    sha256_checksum=checksum,
                    status="registered",
                    discovered_at=fixed_time,
                    registered_at=fixed_time,
                )
                session.add(source_file)
                session.flush()
            session.add(
                GeneratedSourceFile(
                    tenant_id=tenant.id,
                    generated_dataset_run_id=run.id,
                    source_system_id=source_system.id,
                    source_file_id=source_file.id,
                    file_type=file_type,
                    filename=filename,
                    relative_path=f"generated/clean/{tenant.code}/run_{run.id:08d}/{filename}",
                    sha256_checksum=checksum,
                    file_size_bytes=len(content),
                    record_count=len(rows[file_type]),
                    column_count=len(HEADERS[file_type]),
                    metadata_json={"generator_version": run.generator_version},
                )
            )

    def _artifacts(
        self,
        session: Session,
        tenant: Tenant,
        run: GeneratedDatasetRun,
        rows: dict[str, list[dict[str, Any]]],
        files: dict[str, bytes],
        links: list[Any],
        controls: list[Any],
    ) -> None:
        root = self.settings.GENERATED_DATA_DIRECTORY.resolve()
        artifact_dir = root / "manifests" / tenant.code / f"run_{run.id:08d}"
        report_dir = root / "reports" / tenant.code / f"run_{run.id:08d}"
        artifact_dir.mkdir(parents=True, exist_ok=False)
        report_dir.mkdir(parents=True, exist_ok=False)
        inventory = [
            {"filename": f"{name}.csv", "row_count": len(rows[name]), "sha256": _sha(files[name])}
            for name in FILE_ORDER
        ]
        manifest = {
            "tenant_code": tenant.code,
            "generator_version": run.generator_version,
            "random_seed": run.random_seed,
            "generation_date": run.generation_date.isoformat(),
            "input_fingerprint": run.input_fingerprint,
            "source_canonical_date_range": {
                "start": run.base_date_start.isoformat() if run.base_date_start else None,
                "end": run.base_date_end.isoformat() if run.base_date_end else None,
            },
            "canonical_records_used": {
                "bank_transactions": run.source_bank_transaction_count,
                "credit_card_transactions": run.source_credit_card_transaction_count,
                "payroll_runs": run.source_payroll_run_count,
            },
            "generated_files": inventory,
            "relationship_count": len(links),
            "control_totals": [
                {
                    "name": n,
                    "expected": str(e),
                    "actual": str(a),
                    "status": "passed" if e == a else "failed",
                }
                for n, e, a in controls
            ],
            "generation_exceptions": [],
            "accounting_assumptions": [
                "accrual invoices and AP",
                "card purchases credit card payable",
                "bank-linked payments use exact one-to-one matching",
            ],
            "rounding_policy": "Decimal ROUND_HALF_UP to 0.01",
            "stable_identifier_rules": (
                "human-readable sequential identifiers after stable source ordering"
            ),
            "run_status": "completed",
            "production_rules": {
                name: (
                    "deterministically derived from canonical history and configured "
                    "clean-data rules"
                )
                for name in FILE_ORDER
            },
        }
        artifacts: tuple[tuple[Path, Any, str], ...] = (
            (artifact_dir / "generation_manifest.json", manifest, "generation_manifest"),
            (
                artifact_dir / "relationship_manifest.json",
                {"links": links},
                "relationship_manifest",
            ),
            (
                report_dir / "control_totals.json",
                {
                    "controls": [
                        {"name": name, "expected": str(expected), "actual": str(actual)}
                        for name, expected, actual in controls
                    ]
                },
                "control_total_report",
            ),
            (
                report_dir / "generation_exceptions.json",
                {"exceptions": []},
                "generation_exception_report",
            ),
            (
                report_dir / "generated_file_inventory.json",
                {"files": inventory},
                "generated_file_inventory",
            ),
        )
        for path, value, artifact_type in artifacts:
            content = _canonical_json(value)
            path.write_bytes(content)
            relative = path.resolve().relative_to(root).as_posix()
            session.add(
                PipelineRunArtifact(
                    tenant_id=tenant.id,
                    pipeline_run_id=run.pipeline_run_id,
                    artifact_type=artifact_type,
                    name=path.name,
                    relative_path=f"generated/{relative}",
                    checksum=_sha(content),
                    mime_type="application/json",
                    file_size_bytes=len(content),
                    metadata_json={"immutable": True},
                )
            )

    def _verify_physical_files(self, session: Session, run: GeneratedDatasetRun) -> None:
        root = self.settings.GENERATED_DATA_DIRECTORY.resolve()
        for item in session.scalars(
            select(GeneratedSourceFile).where(
                GeneratedSourceFile.generated_dataset_run_id == run.id
            )
        ):
            relative = Path(item.relative_path).relative_to("generated")
            path = (root / relative).resolve()
            if (
                root not in path.parents
                or not path.is_file()
                or _sha(path.read_bytes()) != item.sha256_checksum
            ):
                raise GenerationError(f"Generated file verification failed: {item.filename}")
