import os
import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://pipeline:pipeline@postgres:5432/pipeline"
)

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AuditEvent,
    AuditEventChange,
    BankTransaction,
    CanonicalRecordLineage,
    Counterparty,
    CreditCardTransaction,
    DataMutation,
    DataQualityIssue,
    Employee,
    ExpectedException,
    FinancialTransaction,
    GeneratedDatasetRun,
    GeneratedRecordLink,
    GeneratedSourceFile,
    GenerationControlTotal,
    GenerationException,
    IngestionControlTotal,
    MessyDatasetRun,
    MessyGenerationControlTotal,
    MessySourceFile,
    NormalizationControlTotal,
    NormalizationException,
    PayrollEntry,
    PayrollRun,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    RawSourceRow,
    RejectedSourceRow,
    SourceFile,
    SourceFileColumnProfile,
    SourceFileProfile,
    StagingBankTransaction,
    StagingCreditCardTransaction,
    StagingPayrollDetail,
    StagingPayrollSummary,
    ValidationIssue,
    ValidationIssueHistory,
    ValidationReport,
    ValidationRun,
    ValidationRunResult,
    ValidationStatistic,
    ValidationSummary,
    Vendor,
)
from app.services.governance_seed import seed_governance_data


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        DATABASE_URL=os.environ["DATABASE_URL"],
        UPLOAD_TEMP_DIRECTORY=tmp_path / "raw" / "uploads",
        REGISTERED_RAW_DIRECTORY=tmp_path / "raw" / "registered",
        REJECTED_RAW_DIRECTORY=tmp_path / "raw" / "rejected",
        MANIFESTS_DIRECTORY=tmp_path / "manifests",
        INGESTION_REPORTS_DIRECTORY=tmp_path / "reports",
        GENERATED_DATA_DIRECTORY=tmp_path / "generated",
        MESSY_GENERATED_ROOT=tmp_path / "generated" / "messy",
        MESSY_MANIFEST_ROOT=tmp_path / "generated" / "manifests" / "messy",
        MESSY_REPORT_ROOT=tmp_path / "generated" / "reports" / "messy",
        VALIDATION_REPORT_ROOT=tmp_path / "generated" / "reports" / "validation",
        MAX_UPLOAD_SIZE_BYTES=128,
    )


@pytest.fixture(autouse=True)
def isolate_registration_records(tmp_path: Path) -> Generator[None, None, None]:
    with SessionLocal() as session:
        seed_governance_data(session, get_settings())
        baseline_run_id = session.scalar(select(func.max(PipelineRun.id))) or 0
        baseline_file_id = session.scalar(select(func.max(SourceFile.id))) or 0
        baseline_audit_id = session.scalar(select(func.max(AuditEvent.id))) or 0
        baseline_counterparty_id = session.scalar(select(func.max(Counterparty.id))) or 0
        baseline_employee_id = session.scalar(select(func.max(Employee.id))) or 0
        baseline_vendor_id = session.scalar(select(func.max(Vendor.id))) or 0
    yield
    with SessionLocal() as session:
        new_audit_ids = select(AuditEvent.id).where(AuditEvent.id > baseline_audit_id)
        session.execute(
            delete(AuditEventChange).where(AuditEventChange.audit_event_id.in_(new_audit_ids))
        )
        session.execute(delete(AuditEvent).where(AuditEvent.id > baseline_audit_id))
        new_run_ids = select(PipelineRun.id).where(PipelineRun.id > baseline_run_id)
        new_profile_ids = select(SourceFileProfile.id).where(
            SourceFileProfile.pipeline_run_id.in_(new_run_ids)
        )
        new_transaction_ids = select(FinancialTransaction.id).where(
            FinancialTransaction.normalization_run_id.in_(new_run_ids)
        )
        new_payroll_run_ids = select(PayrollRun.id).where(
            PayrollRun.pipeline_run_id.in_(new_run_ids)
        )
        new_generated_run_ids = select(GeneratedDatasetRun.id).where(
            GeneratedDatasetRun.pipeline_run_id.in_(new_run_ids)
        )
        new_messy_run_ids = select(MessyDatasetRun.id).where(
            MessyDatasetRun.pipeline_run_id.in_(new_run_ids)
        )
        new_validation_run_ids = select(ValidationRun.id).where(
            ValidationRun.pipeline_run_id.in_(new_run_ids)
        )
        new_validation_issue_ids = select(ValidationIssue.id).where(
            ValidationIssue.validation_run_id.in_(new_validation_run_ids)
        )
        session.execute(
            delete(ValidationIssueHistory).where(
                ValidationIssueHistory.validation_issue_id.in_(new_validation_issue_ids)
            )
        )
        session.execute(
            delete(ValidationIssue).where(
                ValidationIssue.validation_run_id.in_(new_validation_run_ids)
            )
        )
        session.execute(
            delete(ValidationRunResult).where(
                ValidationRunResult.validation_run_id.in_(new_validation_run_ids)
            )
        )
        session.execute(
            delete(ValidationReport).where(
                ValidationReport.validation_run_id.in_(new_validation_run_ids)
            )
        )
        session.execute(
            delete(ValidationStatistic).where(
                ValidationStatistic.validation_run_id.in_(new_validation_run_ids)
            )
        )
        session.execute(
            delete(ValidationSummary).where(
                ValidationSummary.validation_run_id.in_(new_validation_run_ids)
            )
        )
        session.execute(delete(ValidationRun).where(ValidationRun.id.in_(new_validation_run_ids)))
        session.execute(
            delete(ExpectedException).where(
                ExpectedException.messy_dataset_run_id.in_(new_messy_run_ids)
            )
        )
        session.execute(
            delete(DataMutation).where(DataMutation.messy_dataset_run_id.in_(new_messy_run_ids))
        )
        session.execute(
            delete(MessyGenerationControlTotal).where(
                MessyGenerationControlTotal.messy_dataset_run_id.in_(new_messy_run_ids)
            )
        )
        session.execute(
            delete(MessySourceFile).where(
                MessySourceFile.messy_dataset_run_id.in_(new_messy_run_ids)
            )
        )
        session.execute(delete(MessyDatasetRun).where(MessyDatasetRun.id.in_(new_messy_run_ids)))
        session.execute(
            delete(GeneratedRecordLink).where(
                GeneratedRecordLink.generated_dataset_run_id.in_(new_generated_run_ids)
            )
        )
        session.execute(
            delete(GenerationControlTotal).where(
                GenerationControlTotal.generated_dataset_run_id.in_(new_generated_run_ids)
            )
        )
        session.execute(
            delete(GenerationException).where(
                GenerationException.generated_dataset_run_id.in_(new_generated_run_ids)
            )
        )
        session.execute(
            delete(GeneratedSourceFile).where(
                GeneratedSourceFile.generated_dataset_run_id.in_(new_generated_run_ids)
            )
        )
        session.execute(
            delete(GeneratedDatasetRun).where(GeneratedDatasetRun.id.in_(new_generated_run_ids))
        )
        session.execute(
            delete(CanonicalRecordLineage).where(
                CanonicalRecordLineage.source_file_id > baseline_file_id
            )
        )
        session.execute(
            delete(BankTransaction).where(
                BankTransaction.financial_transaction_id.in_(new_transaction_ids)
            )
        )
        session.execute(
            delete(CreditCardTransaction).where(
                CreditCardTransaction.financial_transaction_id.in_(new_transaction_ids)
            )
        )
        session.execute(
            delete(PayrollEntry).where(PayrollEntry.payroll_run_id.in_(new_payroll_run_ids))
        )
        session.execute(
            delete(FinancialTransaction).where(
                FinancialTransaction.normalization_run_id.in_(new_run_ids)
            )
        )
        session.execute(delete(PayrollRun).where(PayrollRun.id.in_(new_payroll_run_ids)))
        session.execute(
            delete(NormalizationException).where(
                NormalizationException.pipeline_run_id.in_(new_run_ids)
            )
        )
        session.execute(
            delete(NormalizationControlTotal).where(
                NormalizationControlTotal.pipeline_run_id.in_(new_run_ids)
            )
        )
        session.execute(
            delete(StagingBankTransaction).where(
                StagingBankTransaction.pipeline_run_id.in_(new_run_ids)
            )
        )
        session.execute(
            delete(StagingCreditCardTransaction).where(
                StagingCreditCardTransaction.pipeline_run_id.in_(new_run_ids)
            )
        )
        session.execute(
            delete(StagingPayrollSummary).where(
                StagingPayrollSummary.pipeline_run_id.in_(new_run_ids)
            )
        )
        session.execute(
            delete(StagingPayrollDetail).where(
                StagingPayrollDetail.pipeline_run_id.in_(new_run_ids)
            )
        )
        session.execute(
            delete(RejectedSourceRow).where(RejectedSourceRow.pipeline_run_id.in_(new_run_ids))
        )
        session.execute(
            delete(IngestionControlTotal).where(
                IngestionControlTotal.pipeline_run_id.in_(new_run_ids)
            )
        )
        session.execute(delete(RawSourceRow).where(RawSourceRow.pipeline_run_id.in_(new_run_ids)))
        session.execute(
            delete(DataQualityIssue).where(
                DataQualityIssue.source_file_profile_id.in_(new_profile_ids)
            )
        )
        session.execute(
            delete(SourceFileColumnProfile).where(
                SourceFileColumnProfile.source_file_profile_id.in_(new_profile_ids)
            )
        )
        session.execute(delete(SourceFileProfile).where(SourceFileProfile.id.in_(new_profile_ids)))
        session.execute(
            delete(PipelineRunStep).where(PipelineRunStep.pipeline_run_id.in_(new_run_ids))
        )
        session.execute(
            delete(PipelineRunArtifact).where(PipelineRunArtifact.pipeline_run_id.in_(new_run_ids))
        )
        session.execute(delete(PipelineRun).where(PipelineRun.id > baseline_run_id))
        session.execute(delete(SourceFile).where(SourceFile.id > baseline_file_id))
        session.execute(delete(Employee).where(Employee.id > baseline_employee_id))
        session.execute(delete(Vendor).where(Vendor.id > baseline_vendor_id))
        session.execute(delete(Counterparty).where(Counterparty.id > baseline_counterparty_id))
        session.commit()
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture
def client(test_settings: Settings) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(
        app,
        headers={
            "X-Tenant-Code": "demo_coffee_group",
            "X-Demo-User": "analyst@demo.local",
        },
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
