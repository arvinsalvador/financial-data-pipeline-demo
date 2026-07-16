from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    GeneratedSourceFile,
    Permission,
    PipelineDefinition,
    PipelineRunArtifact,
    SourceFile,
    SourceSystem,
    Tenant,
    ValidationRule,
)
from app.services.governance_seed import seed_governance_data


class DemoEnvironmentError(ValueError):
    pass


@dataclass(frozen=True)
class CleanupFile:
    mode: str
    path: Path


def require_development(settings: Settings) -> None:
    if settings.ENVIRONMENT not in {"development", "test"}:
        raise DemoEnvironmentError(
            f"Demo environment utilities are disabled in {settings.ENVIRONMENT!r}"
        )


def data_root(settings: Settings) -> Path:
    return settings.REGISTERED_RAW_DIRECTORY.resolve().parents[1]


def safe_path(path: Path, settings: Settings) -> Path:
    root = data_root(settings)
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise DemoEnvironmentError(f"Cleanup path is outside the configured data root: {resolved}")
    if resolved.name == ".env" or ".git" in resolved.parts:
        raise DemoEnvironmentError(f"Protected path cannot be changed: {resolved}")
    return resolved


def cleanup_files(settings: Settings, modes: set[str]) -> list[CleanupFile]:
    roots: dict[str, list[Path]] = {
        "uploaded_files": [
            settings.UPLOAD_TEMP_DIRECTORY,
            settings.REGISTERED_RAW_DIRECTORY,
            settings.REJECTED_RAW_DIRECTORY,
        ],
        "generated_clean": [settings.GENERATED_DATA_DIRECTORY],
        "generated_messy": [settings.MESSY_GENERATED_ROOT],
        "reports": [
            settings.INGESTION_REPORTS_DIRECTORY,
            settings.MESSY_REPORT_ROOT,
            settings.VALIDATION_REPORT_ROOT,
            settings.RECONCILIATION_REPORT_ROOT,
            settings.PAYROLL_RECONCILIATION_REPORT_ROOT,
        ],
        "manifests": [settings.MANIFESTS_DIRECTORY, settings.MESSY_MANIFEST_ROOT],
    }
    exclusions = {
        safe_path(settings.MESSY_GENERATED_ROOT, settings),
        safe_path(settings.GENERATED_DATA_DIRECTORY / "manifests", settings),
        safe_path(settings.GENERATED_DATA_DIRECTORY / "reports", settings),
        safe_path(settings.MESSY_MANIFEST_ROOT, settings),
        safe_path(settings.MESSY_REPORT_ROOT, settings),
        safe_path(settings.VALIDATION_REPORT_ROOT, settings),
    }
    found: dict[Path, CleanupFile] = {}
    for mode in sorted(modes):
        for configured in roots.get(mode, []):
            root = safe_path(configured, settings)
            if not root.exists():
                continue
            for candidate in root.rglob("*"):
                resolved = safe_path(candidate, settings)
                if not resolved.is_file() or resolved.name == ".gitkeep":
                    continue
                if mode == "generated_clean" and any(
                    resolved == excluded or excluded in resolved.parents for excluded in exclusions
                ):
                    continue
                found[resolved] = CleanupFile(mode, resolved)
    return [found[path] for path in sorted(found, key=str)]


def remove_files(files: list[CleanupFile]) -> None:
    for item in files:
        item.path.unlink()


DEMO_DATA_TABLES = (
    "audit_event_changes",
    "payroll_reconciliation_decisions",
    "payroll_reconciliation_allocations",
    "payroll_reconciliation_matches",
    "payroll_reconciliation_exceptions",
    "payroll_reconciliation_reports",
    "payroll_reconciliation_control_totals",
    "payroll_reconciliation_groups",
    "payroll_reconciliation_candidates",
    "payroll_reconciliation_runs",
    "reconciliation_decisions",
    "reconciliation_allocations",
    "reconciliation_matches",
    "reconciliation_exceptions",
    "reconciliation_reports",
    "reconciliation_control_totals",
    "reconciliation_match_groups",
    "reconciliation_candidates",
    "bank_ledger_reconciliation_runs",
    "validation_issue_history",
    "validation_issues",
    "validation_run_results",
    "validation_reports",
    "validation_statistics",
    "validation_summaries",
    "validation_runs",
    "expected_exceptions",
    "data_mutations",
    "messy_generation_control_totals",
    "messy_source_files",
    "messy_dataset_runs",
    "generated_record_links",
    "generation_control_totals",
    "generation_exceptions",
    "generated_source_files",
    "generated_dataset_runs",
    "canonical_record_lineage",
    "bank_transactions",
    "credit_card_transactions",
    "payroll_entries",
    "financial_transactions",
    "payroll_runs",
    "normalization_exceptions",
    "normalization_control_totals",
    "staging_bank_transactions",
    "staging_credit_card_transactions",
    "staging_payroll_details",
    "staging_payroll_summaries",
    "rejected_source_rows",
    "ingestion_control_totals",
    "raw_source_rows",
    "data_quality_issues",
    "source_file_column_profiles",
    "source_file_profiles",
    "pipeline_run_artifacts",
    "pipeline_run_steps",
    "audit_events",
    "pipeline_runs",
    "source_files",
)


def database_counts(session: Session) -> dict[str, int]:
    return {
        table: int(session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
        for table in DEMO_DATA_TABLES
    }


def reset_database_records(session: Session) -> None:
    quoted = ", ".join(f'"{table}"' for table in DEMO_DATA_TABLES)
    session.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    session.commit()


def bootstrap_demo(session: Session, settings: Settings) -> dict[str, int]:
    require_development(settings)
    return seed_governance_data(session, settings)


def _resolved_relative(relative_path: str, settings: Settings) -> Path:
    if Path(relative_path).is_absolute():
        raise DemoEnvironmentError(f"Absolute stored path: {relative_path}")
    return safe_path(data_root(settings) / relative_path, settings)


def verify_demo(session: Session, settings: Settings) -> list[str]:
    require_development(settings)
    issues: list[str] = []
    registered: set[Path] = set()
    for record in session.scalars(select(SourceFile).order_by(SourceFile.id)):
        try:
            path = _resolved_relative(record.relative_path, settings)
            registered.add(path)
            if not path.is_file():
                issues.append(
                    f"missing_registered_file source_file={record.id} path={record.relative_path}"
                )
        except DemoEnvironmentError as error:
            issues.append(f"invalid_source_path source_file={record.id} {error}")
    registered_root = safe_path(settings.REGISTERED_RAW_DIRECTORY, settings)
    if registered_root.exists():
        for path in registered_root.rglob("*"):
            if path.is_file() and path.name != ".gitkeep" and path.resolve() not in registered:
                issues.append(
                    f"orphan_registered_file path={path.relative_to(data_root(settings))}"
                )
    for generated in session.scalars(select(GeneratedSourceFile).order_by(GeneratedSourceFile.id)):
        try:
            path = _resolved_relative(generated.relative_path, settings)
            if not path.is_file():
                issues.append(
                    f"missing_generated_source id={generated.id} path={generated.relative_path}"
                )
        except DemoEnvironmentError as error:
            issues.append(f"invalid_generated_source_path id={generated.id} {error}")
    for artifact in session.scalars(select(PipelineRunArtifact).order_by(PipelineRunArtifact.id)):
        try:
            path = _resolved_relative(artifact.relative_path, settings)
            if not path.is_file():
                issues.append(
                    f"missing_pipeline_artifact id={artifact.id} path={artifact.relative_path}"
                )
        except DemoEnvironmentError as error:
            issues.append(f"invalid_pipeline_artifact_path id={artifact.id} {error}")
    duplicates = session.execute(
        select(SourceFile.sha256_checksum, func.count())
        .group_by(SourceFile.sha256_checksum)
        .having(func.count() > 1)
    ).all()
    for checksum, count in duplicates:
        issues.append(f"duplicate_registered_checksum checksum={checksum} count={count}")
    required = {
        "tenants": session.scalar(select(func.count()).select_from(Tenant)) or 0,
        "source_systems": session.scalar(select(func.count()).select_from(SourceSystem)) or 0,
        "permissions": session.scalar(select(func.count()).select_from(Permission)) or 0,
        "pipelines": session.scalar(select(func.count()).select_from(PipelineDefinition)) or 0,
        "validation_rules": session.scalar(select(func.count()).select_from(ValidationRule)) or 0,
    }
    for name, count in required.items():
        if not count:
            issues.append(f"missing_bootstrap_records type={name}")
    current = session.scalar(text("SELECT version_num FROM alembic_version"))
    config = Config("alembic.ini")
    expected = ScriptDirectory.from_config(config).get_current_head()
    if current != expected:
        issues.append(f"alembic_revision_mismatch current={current} expected={expected}")
    return sorted(issues)
