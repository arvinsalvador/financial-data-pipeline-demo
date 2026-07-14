import csv
import hashlib
import io
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    DataMutation,
    ExpectedException,
    FinancialTransaction,
    GeneratedDatasetRun,
    GeneratedSourceFile,
    GenerationControlTotal,
    IngestionControlTotal,
    MessyDatasetRun,
    MessyGenerationControlTotal,
    MessySourceFile,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    SourceFile,
    Tenant,
    ValidationIssue,
    ValidationIssueHistory,
    ValidationReport,
    ValidationRule,
    ValidationRuleSet,
    ValidationRun,
    ValidationRunResult,
    ValidationStatistic,
    ValidationSummary,
)
from app.services.validation_engine import (
    ValidationContext,
    ValidationDocument,
    ValidationFinding,
    ValidationRuleRegistry,
)

STEPS = (
    "validate_schema",
    "validate_required_fields",
    "validate_identifiers",
    "validate_dates",
    "validate_amounts",
    "validate_duplicates",
    "validate_relationships",
    "validate_financial_rules",
    "validate_business_rules",
    "validate_control_totals",
    "build_summary",
    "generate_reports",
    "finalize_validation",
)
RULE_IMPLEMENTATION = "phase8_validation_rules_v7"


class ValidationEngineError(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ValidationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = ValidationRuleRegistry()

    def run(
        self,
        session: Session,
        tenant: Tenant,
        target_type: str,
        target_id: int | None,
        rule_set_code: str | None = None,
        force_rerun: bool = False,
    ) -> tuple[ValidationRun, bool]:
        allowed = {"tenant", "source_file", "pipeline", "generated_dataset", "messy_dataset"}
        if target_type not in allowed:
            raise ValidationEngineError(f"Unsupported validation target: {target_type}")
        if target_type != "tenant" and target_id is None:
            raise ValidationEngineError("target_id is required for this target type")
        rule_set = session.scalar(
            select(ValidationRuleSet).where(
                ValidationRuleSet.tenant_id == tenant.id,
                ValidationRuleSet.code
                == (rule_set_code or self.settings.DEFAULT_VALIDATION_RULE_SET),
                ValidationRuleSet.is_active.is_(True),
            )
        )
        if rule_set is None:
            raise ValidationEngineError("Active validation rule set not found")
        rules = list(
            session.scalars(
                select(ValidationRule)
                .where(ValidationRule.validation_rule_set_id == rule_set.id)
                .order_by(ValidationRule.execution_order)
            )
        )
        documents, links, controls, target_payload = self._load_target(
            session, tenant, target_type, target_id
        )
        rule_payload = [
            {
                "code": rule.code,
                "version": rule.version,
                "enabled": rule.is_enabled,
                "severity": rule.severity,
                "target": rule.target_entity,
                "configuration": rule.configuration_json or {},
                "order": rule.execution_order,
            }
            for rule in rules
        ]
        input_fingerprint = _sha(
            _json_bytes(
                {
                    "tenant": tenant.code,
                    "validation_version": self.settings.VALIDATION_VERSION,
                    "rule_implementation": RULE_IMPLEMENTATION,
                    "rule_set": rule_set.code,
                    "rule_set_version": rule_set.version,
                    "rules": rule_payload,
                    "target_type": target_type,
                    "target_id": target_id,
                    "target": target_payload,
                }
            )
        )
        existing = session.scalar(
            select(ValidationRun).where(
                ValidationRun.tenant_id == tenant.id,
                ValidationRun.rule_set_id == rule_set.id,
                ValidationRun.target_type == target_type,
                ValidationRun.input_fingerprint == input_fingerprint,
                ValidationRun.validation_version == self.settings.VALIDATION_VERSION,
                ValidationRun.status.in_(("completed", "completed_with_issues")),
            )
        )
        if existing is not None:
            if force_rerun:
                self.verify(session, tenant.id, existing.id)
            return existing, True
        definition = session.scalar(
            select(PipelineDefinition).where(
                PipelineDefinition.code == "validation_engine",
                PipelineDefinition.version == self.settings.VALIDATION_VERSION,
            )
        )
        if definition is None:
            raise ValidationEngineError("Validation pipeline is not seeded")
        started = datetime.now(UTC)
        pipeline = PipelineRun(
            tenant_id=tenant.id,
            pipeline_definition_id=definition.id,
            run_type="validation_engine",
            status="running",
            started_at=started,
            source_file_id=links.get("source_file_id"),
            metadata_json={
                "validation_version": self.settings.VALIDATION_VERSION,
                "rule_set": rule_set.code,
                "target_type": target_type,
                "target_id": target_id,
                "input_fingerprint": input_fingerprint,
            },
        )
        session.add(pipeline)
        session.flush()
        run = ValidationRun(
            tenant_id=tenant.id,
            pipeline_run_id=pipeline.id,
            rule_set_id=rule_set.id,
            validation_version=self.settings.VALIDATION_VERSION,
            target_type=target_type,
            target_id=target_id,
            source_file_id=links.get("source_file_id"),
            generated_dataset_run_id=links.get("generated_dataset_run_id"),
            messy_dataset_run_id=links.get("messy_dataset_run_id"),
            input_fingerprint=input_fingerprint,
            status="running",
            started_at=started,
            total_rules=len(rules),
            metadata_json={"rule_set_code": rule_set.code, "target": target_payload},
        )
        session.add(run)
        session.flush()
        context = ValidationContext(
            session,
            tenant.id,
            target_type,
            target_id,
            documents,
            controls,
            links.get("expected_exception_count", 0),
            links.get("applied_mutation_count", 0),
        )
        engine_started = perf_counter()
        issues: list[ValidationIssue] = []
        status_counts: Counter[str] = Counter()
        try:
            for rule in rules:
                rule_started = perf_counter()
                findings: list[ValidationFinding]
                details: dict[str, Any]
                outcome_status: str
                evaluated: int
                if not rule.is_enabled:
                    outcome_status, findings, evaluated, details = (
                        "disabled",
                        [],
                        0,
                        {"reason": "rule disabled"},
                    )
                else:
                    plugin = self.registry.get(rule.code)
                    if plugin is None:
                        outcome_status, findings, evaluated, details = (
                            "skipped",
                            [],
                            0,
                            {"reason": "plugin unavailable"},
                        )
                    else:
                        try:
                            outcome = plugin.execute(context)
                            findings = outcome.findings[
                                : self.settings.VALIDATION_MAX_ISSUES_PER_RULE
                            ]
                            outcome_status = outcome.status
                            evaluated = outcome.records_evaluated
                            details = {
                                **outcome.details,
                                "truncated": len(outcome.findings) > len(findings),
                            }
                        except Exception as error:
                            outcome_status, evaluated = "failed", 0
                            details = {"execution_error": str(error)}
                            findings = [
                                ValidationFinding(
                                    "RULE_EXECUTION_FAILED",
                                    "engine",
                                    rule.target_entity,
                                    f"Validation rule {rule.code} failed: {error}",
                                )
                            ]
                duration = max(0, int((perf_counter() - rule_started) * 1000))
                status_counts[outcome_status] += 1
                result = ValidationRunResult(
                    tenant_id=tenant.id,
                    validation_run_id=run.id,
                    validation_rule_id=rule.id,
                    validation_version=self.settings.VALIDATION_VERSION,
                    status=outcome_status,
                    records_evaluated=evaluated,
                    issue_count=len(findings),
                    duration_ms=duration,
                    details_json=details,
                )
                session.add(result)
                for ordinal, finding in enumerate(findings, 1):
                    fingerprint = _sha(
                        _json_bytes(
                            {
                                "input": input_fingerprint,
                                "rule": rule.code,
                                "code": finding.code,
                                "file": finding.filename,
                                "row": finding.row_number,
                                "column": finding.column,
                                "entity": finding.entity_type,
                                "entity_key": finding.entity_key,
                                "observed": finding.observed,
                                "ordinal": ordinal,
                            }
                        )
                    )
                    issue = ValidationIssue(
                        tenant_id=tenant.id,
                        validation_run_id=run.id,
                        validation_rule_id=rule.id,
                        validation_version=self.settings.VALIDATION_VERSION,
                        issue_code=finding.code,
                        issue_type=finding.issue_type,
                        severity="critical"
                        if finding.code == "RULE_EXECUTION_FAILED"
                        else rule.severity,
                        status="open",
                        entity_type=finding.entity_type,
                        entity_key=finding.entity_key,
                        source_file_id=finding.source_file_id,
                        filename=finding.filename,
                        row_number=finding.row_number,
                        column_name=finding.column,
                        message=finding.message,
                        observed_value=finding.observed,
                        expected_value=finding.expected,
                        issue_fingerprint=fingerprint,
                        metadata_json={"rule_code": rule.code, **finding.metadata},
                        detected_at=started,
                    )
                    session.add(issue)
                    session.flush()
                    session.add(
                        ValidationIssueHistory(
                            validation_issue_id=issue.id,
                            from_status=None,
                            to_status="open",
                            reason="detected",
                            metadata_json={"validation_version": self.settings.VALIDATION_VERSION},
                        )
                    )
                    issues.append(issue)
            severity = Counter(issue.severity for issue in issues)
            by_rule = Counter(
                (issue.metadata_json or {}).get("rule_code", "unknown") for issue in issues
            )
            by_file = Counter(issue.filename or "database" for issue in issues)
            by_entity = Counter(issue.entity_type for issue in issues)
            for severity_name in ("information", "warning", "error", "critical"):
                severity.setdefault(severity_name, 0)
            for configured_rule in rules:
                by_rule.setdefault(configured_rule.code, 0)
            for validation_document in documents.values():
                by_file.setdefault(validation_document.filename, 0)
                by_entity.setdefault(validation_document.file_type, 0)
            control_payload = {
                "statuses": controls,
                "expected_exception_count": context.expected_exception_count,
                "applied_mutation_count": context.applied_mutation_count,
            }
            summary_payload = {
                "validation_version": self.settings.VALIDATION_VERSION,
                "input_fingerprint": input_fingerprint,
                "issues": len(issues),
                "by_severity": dict(sorted(severity.items())),
                "by_rule": dict(sorted(by_rule.items())),
                "by_file": dict(sorted(by_file.items())),
                "by_entity": dict(sorted(by_entity.items())),
                "controls": control_payload,
            }
            summary_fingerprint = _sha(_json_bytes(summary_payload))
            overall = "failed" if severity["critical"] else "issues" if issues else "passed"
            summary = ValidationSummary(
                tenant_id=tenant.id,
                validation_run_id=run.id,
                validation_version=self.settings.VALIDATION_VERSION,
                overall_status=overall,
                issue_count=len(issues),
                counts_by_severity_json=dict(severity),
                counts_by_rule_json=dict(by_rule),
                counts_by_file_json=dict(by_file),
                counts_by_entity_json=dict(by_entity),
                control_totals_json=control_payload,
                summary_fingerprint=summary_fingerprint,
            )
            session.add(summary)
            run.records_evaluated = context.record_count
            for dimension, counts in (
                ("severity", severity),
                ("rule", by_rule),
                ("file", by_file),
                ("entity", by_entity),
            ):
                for key, count in sorted(counts.items()):
                    session.add(
                        ValidationStatistic(
                            tenant_id=tenant.id,
                            validation_run_id=run.id,
                            dimension_type=dimension,
                            dimension_key=str(key),
                            issue_count=count,
                            records_evaluated=context.record_count,
                            details_json={},
                        )
                    )
            self._reports(session, tenant, run, rules, issues, summary_payload, summary_fingerprint)
            completed = datetime.now(UTC)
            run.passed_rules = status_counts["passed"]
            run.failed_rules = status_counts["failed"]
            run.skipped_rules = status_counts["skipped"]
            run.disabled_rules = status_counts["disabled"]
            run.total_issues = len(issues)
            run.information_count = severity["information"]
            run.warning_count = severity["warning"]
            run.error_count = severity["error"]
            run.critical_count = severity["critical"]
            run.duration_ms = max(0, int((perf_counter() - engine_started) * 1000))
            run.status = "completed_with_issues" if issues else "completed"
            run.completed_at = completed
            run.metadata_json = {
                **(run.metadata_json or {}),
                "summary_fingerprint": summary_fingerprint,
                "reports": 7,
            }
            pipeline.status = run.status
            pipeline.completed_at = completed
            pipeline.records_extracted = context.record_count
            pipeline.records_accepted = max(0, context.record_count - len(issues))
            pipeline.records_rejected = len(issues)
            for order, step in enumerate(STEPS, 1):
                session.add(
                    PipelineRunStep(
                        pipeline_run_id=pipeline.id,
                        step_name=step,
                        step_order=order,
                        status="completed",
                        started_at=started,
                        completed_at=completed,
                        metadata_json={"validation_version": self.settings.VALIDATION_VERSION},
                    )
                )
            session.commit()
            session.refresh(run)
            return run, False
        except Exception:
            session.rollback()
            failed_pipeline = session.get(PipelineRun, pipeline.id)
            failed_run = session.get(ValidationRun, run.id)
            if failed_pipeline:
                failed_pipeline.status = "failed"
                failed_pipeline.completed_at = datetime.now(UTC)
            if failed_run:
                failed_run.status = "failed"
                failed_run.completed_at = datetime.now(UTC)
            session.commit()
            raise

    def _load_target(
        self, session: Session, tenant: Tenant, target_type: str, target_id: int | None
    ) -> tuple[dict[str, ValidationDocument], dict[str, int], dict[str, str], dict[str, Any]]:
        documents: dict[str, ValidationDocument] = {}
        links: dict[str, int] = {}
        checksums: dict[str, str] = {}
        if target_type == "source_file":
            source = session.scalar(
                select(SourceFile).where(
                    SourceFile.id == target_id, SourceFile.tenant_id == tenant.id
                )
            )
            if source is None:
                raise ValidationEngineError("Source file not found")
            links["source_file_id"] = source.id
            document = self._source_document(source)
            documents[document.file_type] = document
            checksums[document.filename] = source.sha256_checksum
        elif target_type == "generated_dataset":
            generated = session.scalar(
                select(GeneratedDatasetRun).where(
                    GeneratedDatasetRun.id == target_id, GeneratedDatasetRun.tenant_id == tenant.id
                )
            )
            if generated is None:
                raise ValidationEngineError("Generated dataset not found")
            links["generated_dataset_run_id"] = generated.id
            generated_files = session.scalars(
                select(GeneratedSourceFile)
                .where(GeneratedSourceFile.generated_dataset_run_id == generated.id)
                .order_by(GeneratedSourceFile.file_type)
            ).all()
            for generated_file in generated_files:
                document = self._generated_document(
                    generated_file.file_type,
                    generated_file.filename,
                    generated_file.source_file_id,
                    generated_file.relative_path,
                    generated_file.sha256_checksum,
                )
                documents[generated_file.file_type] = document
                checksums[generated_file.filename] = generated_file.sha256_checksum
        elif target_type == "messy_dataset":
            messy = session.scalar(
                select(MessyDatasetRun).where(
                    MessyDatasetRun.id == target_id, MessyDatasetRun.tenant_id == tenant.id
                )
            )
            if messy is None:
                raise ValidationEngineError("Messy dataset not found")
            links["messy_dataset_run_id"] = messy.id
            links["expected_exception_count"] = (
                session.query(ExpectedException)
                .filter(ExpectedException.messy_dataset_run_id == messy.id)
                .count()
            )
            links["applied_mutation_count"] = (
                session.query(DataMutation)
                .filter(
                    DataMutation.messy_dataset_run_id == messy.id,
                    DataMutation.mutation_status == "applied",
                )
                .count()
            )
            messy_files = session.scalars(
                select(MessySourceFile)
                .where(MessySourceFile.messy_dataset_run_id == messy.id)
                .order_by(MessySourceFile.file_type)
            ).all()
            for messy_file in messy_files:
                document = self._generated_document(
                    messy_file.file_type,
                    messy_file.filename,
                    messy_file.source_file_id,
                    messy_file.relative_path,
                    messy_file.sha256_checksum,
                )
                documents[messy_file.file_type] = document
                checksums[messy_file.filename] = messy_file.sha256_checksum
        elif target_type == "pipeline":
            pipeline = session.scalar(
                select(PipelineRun).where(
                    PipelineRun.id == target_id, PipelineRun.tenant_id == tenant.id
                )
            )
            if pipeline is None:
                raise ValidationEngineError("Pipeline run not found")
            if pipeline.source_file_id:
                source = session.get(SourceFile, pipeline.source_file_id)
                if source:
                    links["source_file_id"] = source.id
                    document = self._source_document(source)
                    documents[document.file_type] = document
                    checksums[document.filename] = source.sha256_checksum
        else:
            latest_messy = session.scalar(
                select(MessyDatasetRun)
                .where(MessyDatasetRun.tenant_id == tenant.id)
                .order_by(MessyDatasetRun.id.desc())
            )
            if latest_messy:
                return self._load_target(session, tenant, "messy_dataset", latest_messy.id)
            latest_generated = session.scalar(
                select(GeneratedDatasetRun)
                .where(GeneratedDatasetRun.tenant_id == tenant.id)
                .order_by(GeneratedDatasetRun.id.desc())
            )
            if latest_generated:
                return self._load_target(session, tenant, "generated_dataset", latest_generated.id)
        controls: dict[str, str] = {}
        for ingestion_control in session.scalars(
            select(IngestionControlTotal).where(IngestionControlTotal.tenant_id == tenant.id)
        ):
            controls[
                f"ingestion:{ingestion_control.pipeline_run_id}:{ingestion_control.control_name}"
            ] = ingestion_control.status
        if links.get("generated_dataset_run_id"):
            for generation_control in session.scalars(
                select(GenerationControlTotal).where(
                    GenerationControlTotal.generated_dataset_run_id
                    == links["generated_dataset_run_id"]
                )
            ):
                controls[f"generated:{generation_control.control_name}"] = generation_control.status
        if links.get("messy_dataset_run_id"):
            for messy_control in session.scalars(
                select(MessyGenerationControlTotal).where(
                    MessyGenerationControlTotal.messy_dataset_run_id
                    == links["messy_dataset_run_id"]
                )
            ):
                controls[f"messy:{messy_control.control_name}"] = messy_control.status
        canonical_hashes = list(
            session.scalars(
                select(FinancialTransaction.canonical_hash)
                .where(FinancialTransaction.tenant_id == tenant.id)
                .order_by(FinancialTransaction.canonical_hash)
            )
        )
        payload = {
            "checksums": checksums,
            "controls": controls,
            "canonical_hashes": canonical_hashes,
            "links": links,
        }
        return documents, links, controls, payload

    def _source_document(self, source: SourceFile) -> ValidationDocument:
        root = self.settings.GENERATED_DATA_DIRECTORY.resolve().parent
        path = (root / source.relative_path).resolve()
        if root not in path.parents or not path.is_file():
            raise ValidationEngineError("Source file path is invalid")
        return self._parse(
            Path(source.original_filename).stem,
            source.original_filename,
            source.id,
            path,
            source.sha256_checksum,
        )

    def _generated_document(
        self, file_type: str, filename: str, source_file_id: int, relative_path: str, checksum: str
    ) -> ValidationDocument:
        root = self.settings.GENERATED_DATA_DIRECTORY.resolve().parent
        path = (root / relative_path).resolve()
        if root not in path.parents or not path.is_file():
            raise ValidationEngineError(f"Generated file path is invalid: {filename}")
        return self._parse(file_type, filename, source_file_id, path, checksum)

    def _parse(
        self, file_type: str, filename: str, source_file_id: int, path: Path, checksum: str
    ) -> ValidationDocument:
        content = path.read_bytes()
        if _sha(content) != checksum:
            raise ValidationEngineError(f"Checksum mismatch: {filename}")
        parsed = list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))
        if not parsed:
            return ValidationDocument(file_type, filename, source_file_id, [], [])
        return ValidationDocument(file_type, filename, source_file_id, parsed[0], parsed[1:])

    def _reports(
        self,
        session: Session,
        tenant: Tenant,
        run: ValidationRun,
        rules: list[ValidationRule],
        issues: list[ValidationIssue],
        summary: dict[str, Any],
        summary_fingerprint: str,
    ) -> None:
        root = self.settings.VALIDATION_REPORT_ROOT.resolve()
        directory = (root / tenant.code / f"run_{run.input_fingerprint[:16]}").resolve()
        if root not in directory.parents or directory.exists():
            raise ValidationEngineError("Validation report path is invalid or already exists")
        directory.mkdir(parents=True)
        issue_rows = [
            {
                "rule": (issue.metadata_json or {}).get("rule_code"),
                "code": issue.issue_code,
                "severity": issue.severity,
                "status": issue.status,
                "entity": issue.entity_type,
                "entity_key": issue.entity_key,
                "filename": issue.filename,
                "row": issue.row_number,
                "column": issue.column_name,
                "message": issue.message,
                "observed": issue.observed_value,
                "expected": issue.expected_value,
                "fingerprint": issue.issue_fingerprint,
            }
            for issue in issues
        ]
        common = {
            "validation_version": self.settings.VALIDATION_VERSION,
            "input_fingerprint": run.input_fingerprint,
            "summary_fingerprint": summary_fingerprint,
            "target_type": run.target_type,
            "target_id": run.target_id,
        }
        payloads = {
            "validation_summary": {**common, **summary},
            "validation_report": {**common, "issues": issue_rows},
            "validation_statistics": {
                **common,
                "records_evaluated": run.records_evaluated,
                "issue_count": len(issues),
            },
            "validation_by_severity": {**common, "counts": summary["by_severity"]},
            "validation_by_rule": {
                **common,
                "counts": summary["by_rule"],
                "rules": [rule.code for rule in rules],
            },
            "validation_by_file": {**common, "counts": summary["by_file"]},
            "validation_by_entity": {**common, "counts": summary["by_entity"]},
        }
        data_root = self.settings.GENERATED_DATA_DIRECTORY.resolve().parent
        for report_type, payload in payloads.items():
            path = directory / f"{report_type}.json"
            content = _json_bytes(payload)
            path.write_bytes(content)
            relative = path.relative_to(data_root).as_posix()
            checksum = _sha(content)
            session.add(
                ValidationReport(
                    tenant_id=tenant.id,
                    validation_run_id=run.id,
                    validation_version=self.settings.VALIDATION_VERSION,
                    report_type=report_type,
                    filename=path.name,
                    relative_path=relative,
                    sha256_checksum=checksum,
                    file_size_bytes=len(content),
                    metadata_json={"immutable": True},
                )
            )
            session.add(
                PipelineRunArtifact(
                    tenant_id=tenant.id,
                    pipeline_run_id=run.pipeline_run_id,
                    artifact_type="validation_report",
                    name=path.name,
                    relative_path=relative,
                    checksum=checksum,
                    mime_type="application/json",
                    file_size_bytes=len(content),
                    metadata_json={
                        "validation_version": self.settings.VALIDATION_VERSION,
                        "report_type": report_type,
                    },
                )
            )

    def verify(self, session: Session, tenant_id: int, run_id: int) -> dict[str, int]:
        run = session.scalar(
            select(ValidationRun).where(
                ValidationRun.id == run_id, ValidationRun.tenant_id == tenant_id
            )
        )
        if run is None:
            raise ValidationEngineError("Validation run not found")
        issues = list(
            session.scalars(
                select(ValidationIssue).where(ValidationIssue.validation_run_id == run.id)
            )
        )
        results = list(
            session.scalars(
                select(ValidationRunResult).where(ValidationRunResult.validation_run_id == run.id)
            )
        )
        reports = list(
            session.scalars(
                select(ValidationReport).where(ValidationReport.validation_run_id == run.id)
            )
        )
        summary = session.scalar(
            select(ValidationSummary).where(ValidationSummary.validation_run_id == run.id)
        )
        if (
            len(issues) != run.total_issues
            or len(results) != run.total_rules
            or len(reports) != 7
            or summary is None
        ):
            raise ValidationEngineError("Validation database counts do not reconcile")
        if len({issue.issue_fingerprint for issue in issues}) != len(issues):
            raise ValidationEngineError("Duplicate validation issue fingerprint")
        severity = Counter(issue.severity for issue in issues)
        if (
            severity["information"],
            severity["warning"],
            severity["error"],
            severity["critical"],
        ) != (run.information_count, run.warning_count, run.error_count, run.critical_count):
            raise ValidationEngineError("Validation severity counts do not reconcile")
        root = self.settings.GENERATED_DATA_DIRECTORY.resolve().parent
        for report in reports:
            path = (root / report.relative_path).resolve()
            if (
                root not in path.parents
                or not path.is_file()
                or _sha(path.read_bytes()) != report.sha256_checksum
            ):
                raise ValidationEngineError(
                    f"Validation report checksum mismatch: {report.filename}"
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("validation_version") != run.validation_version
                or payload.get("input_fingerprint") != run.input_fingerprint
            ):
                raise ValidationEngineError(
                    f"Validation report metadata mismatch: {report.filename}"
                )
        return {
            "rules": len(results),
            "issues": len(issues),
            "reports": len(reports),
            "statistics": session.query(ValidationStatistic)
            .filter(ValidationStatistic.validation_run_id == run.id)
            .count(),
        }
