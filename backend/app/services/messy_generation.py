import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    DataMutation,
    DefectScenario,
    DefectScenarioRule,
    ExpectedException,
    GeneratedDatasetRun,
    GeneratedSourceFile,
    MessyDatasetRun,
    MessyGenerationControlTotal,
    MessySourceFile,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    SourceFile,
    SourceSystem,
    Tenant,
)
from app.services.messy.expected import ExpectedExceptionBuilder, ExpectedIssue
from app.services.messy.mutation_services import MutationDispatcher
from app.services.messy.planner import MutationConflictResolver, MutationPlanner
from app.services.messy.types import CsvDocument, MutationResult, PlannedMutation

STEPS = (
    "validate_tenant_and_permissions",
    "load_clean_generated_dataset",
    "verify_clean_dataset_integrity",
    "load_defect_scenario",
    "calculate_input_and_plan_fingerprints",
    "create_mutation_plan",
    "resolve_mutation_conflicts",
    "copy_clean_files_to_working_area",
    "apply_schema_mutations",
    "apply_row_mutations",
    "apply_relationship_mutations",
    "write_messy_files",
    "create_data_mutation_records",
    "create_expected_exception_records",
    "register_messy_source_files",
    "calculate_messy_generation_controls",
    "verify_clean_files_unchanged",
    "create_manifests_and_reports",
    "validate_output_determinism",
    "finalize_messy_generation",
)


class MessyGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MessyGenerationResult:
    run: MessyDatasetRun
    no_op: bool


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class MessyDatasetService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(
        self,
        session: Session,
        tenant: Tenant,
        clean_run_id: int,
        scenario_code: str | None = None,
        random_seed: int | None = None,
        force_rerun: bool = False,
    ) -> MessyGenerationResult:
        seed = (
            random_seed if random_seed is not None else self.settings.MESSY_GENERATION_RANDOM_SEED
        )
        scenario_name = scenario_code or self.settings.DEFAULT_DEFECT_SCENARIO
        clean_run = session.scalar(
            select(GeneratedDatasetRun).where(
                GeneratedDatasetRun.id == clean_run_id,
                GeneratedDatasetRun.tenant_id == tenant.id,
                GeneratedDatasetRun.status == "completed",
            )
        )
        if clean_run is None:
            raise MessyGenerationError("Completed clean generated dataset not found")
        scenario = session.scalar(
            select(DefectScenario)
            .where(
                DefectScenario.tenant_id == tenant.id,
                DefectScenario.code == scenario_name,
                DefectScenario.is_active.is_(True),
            )
            .order_by(DefectScenario.version.desc())
        )
        if scenario is None:
            raise MessyGenerationError("Active defect scenario not found")
        clean_files = list(
            session.scalars(
                select(GeneratedSourceFile)
                .where(GeneratedSourceFile.generated_dataset_run_id == clean_run.id)
                .order_by(GeneratedSourceFile.file_type)
            )
        )
        if not clean_files:
            raise MessyGenerationError("Clean generated dataset has no files")
        clean_bytes, clean_checksums = self._load_clean(tenant, clean_files)
        documents = {
            item.file_type: CsvDocument.parse(item.file_type, clean_bytes[item.file_type])
            for item in clean_files
        }
        rules = list(
            session.scalars(
                select(DefectScenarioRule)
                .where(DefectScenarioRule.defect_scenario_id == scenario.id)
                .order_by(DefectScenarioRule.rule_order)
            )
        )
        input_fingerprint = _sha(
            _json_bytes(
                {
                    "tenant": tenant.code,
                    "clean_run_fingerprint": clean_run.input_fingerprint,
                    "clean_files": clean_checksums,
                    "messy_generator_version": self.settings.MESSY_GENERATOR_VERSION,
                    "scenario": scenario.code,
                    "scenario_version": scenario.version,
                    "seed": seed,
                }
            )
        )
        plans = MutationPlanner().plan(documents, rules, seed, self.settings.MAX_DEFECTS_PER_RUN)
        plans = MutationConflictResolver().resolve(
            plans, self.settings.SCENARIO_RULE_CONFLICT_POLICY
        )
        plan_payload = [self._plan_dict(plan) for plan in plans]
        plan_fingerprint = _sha(_json_bytes(plan_payload))
        existing = session.scalar(
            select(MessyDatasetRun).where(
                MessyDatasetRun.tenant_id == tenant.id,
                MessyDatasetRun.clean_generated_dataset_run_id == clean_run.id,
                MessyDatasetRun.defect_scenario_id == scenario.id,
                MessyDatasetRun.random_seed == seed,
                MessyDatasetRun.input_fingerprint == input_fingerprint,
                MessyDatasetRun.defect_plan_fingerprint == plan_fingerprint,
                MessyDatasetRun.status.in_(("completed", "completed_with_warnings")),
            )
        )
        if existing is not None:
            if force_rerun:
                self.verify(session, tenant.id, existing.id)
            return MessyGenerationResult(existing, True)
        definition = session.scalar(
            select(PipelineDefinition).where(
                PipelineDefinition.code == "messy_data_generation",
                PipelineDefinition.version == self.settings.MESSY_GENERATOR_VERSION,
            )
        )
        source_system = session.scalar(
            select(SourceSystem).where(
                SourceSystem.tenant_id == tenant.id,
                SourceSystem.code == "generated_demo_business_messy",
                SourceSystem.is_active.is_(True),
            )
        )
        if definition is None or source_system is None:
            raise MessyGenerationError("Run the Phase 7 bootstrap before generation")
        now = datetime.now(UTC)
        pipeline = PipelineRun(
            tenant_id=tenant.id,
            pipeline_definition_id=definition.id,
            run_type="messy_data_generation",
            status="running",
            started_at=now,
            metadata_json={
                "clean_generated_dataset_run_id": clean_run.id,
                "scenario_code": scenario.code,
                "random_seed": seed,
                "messy_generator_version": self.settings.MESSY_GENERATOR_VERSION,
                "input_fingerprint": input_fingerprint,
                "defect_plan_fingerprint": plan_fingerprint,
            },
        )
        session.add(pipeline)
        session.flush()
        run = MessyDatasetRun(
            tenant_id=tenant.id,
            pipeline_run_id=pipeline.id,
            clean_generated_dataset_run_id=clean_run.id,
            defect_scenario_id=scenario.id,
            messy_generator_version=self.settings.MESSY_GENERATOR_VERSION,
            random_seed=seed,
            input_fingerprint=input_fingerprint,
            defect_plan_fingerprint=plan_fingerprint,
            status="running",
            started_at=now,
            clean_file_count=len(clean_files),
            metadata_json={
                "scenario_code": scenario.code,
                "scenario_version": scenario.version,
                "clean_file_integrity": "pending",
            },
        )
        session.add(run)
        session.flush()
        try:
            results = self._apply(documents, plans)
            messy_bytes = {
                name: document.serialize() for name, document in sorted(documents.items())
            }
            inventory = {name: _sha(content) for name, content in messy_bytes.items()}
            issues = [
                ExpectedExceptionBuilder().build(tenant.id, input_fingerprint, result, index)
                for index, result in enumerate(results, 1)
                if result.status == "applied"
            ]
            output_fingerprint = _sha(
                _json_bytes(
                    {
                        "files": inventory,
                        "expectations": [issue.fingerprint for issue in issues],
                        "plan": plan_fingerprint,
                    }
                )
            )
            messy_files = self._write_and_register(
                session,
                tenant,
                run,
                source_system,
                clean_files,
                documents,
                messy_bytes,
                output_fingerprint,
            )
            mutations = self._persist_mutations(
                session, tenant.id, run.id, clean_files, messy_files, results
            )
            self._persist_expectations(session, tenant.id, run.id, results, issues, mutations)
            controls = self._controls(
                session, tenant.id, run.id, clean_files, documents, results, issues, clean_checksums
            )
            self._verify_clean_unchanged(tenant, clean_files, clean_checksums)
            self._artifacts(
                session,
                tenant,
                run,
                scenario,
                plan_payload,
                results,
                issues,
                inventory,
                controls,
                output_fingerprint,
            )
            completed = datetime.now(UTC)
            applied = sum(result.status == "applied" for result in results)
            skipped = sum(result.status == "skipped" for result in results)
            failed = sum(result.status == "failed" for result in results)
            run.output_fingerprint = output_fingerprint
            run.messy_file_count = len(messy_files)
            run.requested_defect_count = len(results)
            run.applied_defect_count = applied
            run.skipped_defect_count = skipped
            run.failed_defect_count = failed
            run.expected_exception_count = len(issues)
            run.status = "completed_with_warnings" if skipped or failed else "completed"
            run.completed_at = completed
            run.metadata_json = {
                **(run.metadata_json or {}),
                "clean_file_integrity": "passed",
                "output_fingerprint": output_fingerprint,
            }
            pipeline.status = run.status
            pipeline.completed_at = completed
            pipeline.records_extracted = sum(len(document.rows) for document in documents.values())
            pipeline.records_accepted = applied
            pipeline.records_rejected = skipped + failed
            for order, name in enumerate(STEPS, 1):
                session.add(
                    PipelineRunStep(
                        pipeline_run_id=pipeline.id,
                        step_name=name,
                        step_order=order,
                        status="completed",
                        started_at=now,
                        completed_at=completed,
                        metadata_json={"applied": applied, "skipped": skipped, "failed": failed},
                    )
                )
            session.commit()
            session.refresh(run)
            return MessyGenerationResult(run, False)
        except Exception as error:
            session.rollback()
            failed_pipeline = session.get(PipelineRun, pipeline.id)
            failed_run = session.get(MessyDatasetRun, run.id)
            if failed_pipeline is not None:
                failed_pipeline.status, failed_pipeline.error_message = "failed", str(error)
                failed_pipeline.completed_at = datetime.now(UTC)
            if failed_run is not None:
                failed_run.status, failed_run.completed_at = "failed", datetime.now(UTC)
            session.commit()
            raise

    def _load_clean(
        self, tenant: Tenant, files: list[GeneratedSourceFile]
    ) -> tuple[dict[str, bytes], dict[str, str]]:
        root = self.settings.GENERATED_DATA_DIRECTORY.resolve()
        content: dict[str, bytes] = {}
        checksums: dict[str, str] = {}
        for item in files:
            try:
                relative = Path(item.relative_path).relative_to("generated")
            except ValueError as error:
                raise MessyGenerationError("Invalid clean generated path") from error
            path = (root / relative).resolve()
            if root not in path.parents or not path.is_file():
                raise MessyGenerationError(f"Clean file missing: {item.filename}")
            data = path.read_bytes()
            if _sha(data) != item.sha256_checksum:
                raise MessyGenerationError(f"Clean checksum mismatch: {item.filename}")
            content[item.file_type], checksums[item.file_type] = data, item.sha256_checksum
        return content, checksums

    @staticmethod
    def _plan_dict(plan: PlannedMutation) -> dict[str, Any]:
        return {
            "rule_code": plan.rule_code,
            "rule_order": plan.rule_order,
            "defect_type": plan.defect_type,
            "file_type": plan.file_type,
            "filename": plan.filename,
            "row_number": plan.clean_row_number,
            "record_key": plan.record_key,
            "column": plan.column,
            "original_value": plan.original_value,
            "proposed_value": plan.proposed_value,
            "severity": plan.severity,
            "expected_codes": plan.expected_codes,
            "status": plan.status,
            "reason": plan.reason,
            "configuration": plan.configuration,
        }

    @staticmethod
    def _apply(
        documents: dict[str, CsvDocument], plans: list[PlannedMutation]
    ) -> list[MutationResult]:
        dispatcher = MutationDispatcher()
        results: list[MutationResult] = []
        for plan in plans:
            results.extend(dispatcher.apply(documents, plan))
        return results

    def _write_and_register(
        self,
        session: Session,
        tenant: Tenant,
        run: MessyDatasetRun,
        source_system: SourceSystem,
        clean_files: list[GeneratedSourceFile],
        documents: dict[str, CsvDocument],
        files: dict[str, bytes],
        output_key: str,
    ) -> dict[str, MessySourceFile]:
        root = self.settings.MESSY_GENERATED_ROOT.resolve()
        output = (root / tenant.code / f"run_{output_key[:16]}").resolve()
        if root not in output.parents or output.exists():
            raise MessyGenerationError("Messy output path is invalid or already exists")
        output.mkdir(parents=True)
        registered = self.settings.REGISTERED_RAW_DIRECTORY.resolve()
        registered.mkdir(parents=True, exist_ok=True)
        clean_by_type = {item.file_type: item for item in clean_files}
        result: dict[str, MessySourceFile] = {}
        for file_type, content in sorted(files.items()):
            filename = f"{file_type}.csv"
            path = output / filename
            path.write_bytes(content)
            checksum = _sha(content)
            source_file = session.scalar(
                select(SourceFile).where(
                    SourceFile.tenant_id == tenant.id, SourceFile.sha256_checksum == checksum
                )
            )
            if source_file is None:
                stored = f"{tenant.code}_messy_{checksum[:16]}_{filename}"
                shutil.copyfile(path, registered / stored)
                clean_run = session.get(GeneratedDatasetRun, run.clean_generated_dataset_run_id)
                if clean_run is None:
                    raise MessyGenerationError("Clean generated dataset disappeared")
                fixed = datetime.combine(
                    clean_run.generation_date,
                    datetime.min.time(),
                    tzinfo=UTC,
                )
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
                    discovered_at=fixed,
                    registered_at=fixed,
                )
                session.add(source_file)
                session.flush()
            item = MessySourceFile(
                tenant_id=tenant.id,
                messy_dataset_run_id=run.id,
                clean_generated_source_file_id=clean_by_type[file_type].id,
                source_file_id=source_file.id,
                file_type=file_type,
                filename=filename,
                relative_path=f"generated/messy/{tenant.code}/run_{output_key[:16]}/{filename}",
                sha256_checksum=checksum,
                file_size_bytes=len(content),
                row_count=len(documents[file_type].rows),
                column_count=len(documents[file_type].headers),
                metadata_json={
                    "dataset_variant": "messy",
                    "scenario_seed": run.random_seed,
                    "messy_generator_version": run.messy_generator_version,
                    "clean_checksum": clean_by_type[file_type].sha256_checksum,
                },
            )
            session.add(item)
            session.flush()
            result[file_type] = item
        return result

    def _truncate(self, value: str | None) -> str | None:
        return value[: self.settings.MAX_MUTATION_VALUE_LENGTH] if value is not None else None

    def _persist_mutations(
        self,
        session: Session,
        tenant_id: int,
        run_id: int,
        clean_files: list[GeneratedSourceFile],
        messy_files: dict[str, MessySourceFile],
        results: list[MutationResult],
    ) -> list[DataMutation]:
        clean = {item.file_type: item for item in clean_files}
        records: list[DataMutation] = []
        messy_run = session.get(MessyDatasetRun, run_id)
        if messy_run is None:
            raise MessyGenerationError("Messy dataset disappeared")
        for ordinal, result in enumerate(results, 1):
            plan = result.plan
            fingerprint = _sha(
                _json_bytes(
                    {
                        "tenant": tenant_id,
                        "run_input": messy_run.input_fingerprint,
                        "rule": plan.rule_code,
                        "file": plan.file_type,
                        "row": plan.clean_row_number,
                        "column": plan.column,
                        "ordinal": ordinal,
                        "original": result.original_value,
                        "mutated": result.mutated_value,
                        "status": result.status,
                    }
                )
            )
            record = DataMutation(
                tenant_id=tenant_id,
                messy_dataset_run_id=run_id,
                source_clean_file_id=clean[plan.file_type].id,
                source_messy_file_id=messy_files[plan.file_type].id,
                defect_scenario_rule_id=plan.rule_id,
                defect_type=plan.defect_type,
                target_file_type=plan.file_type,
                target_filename=plan.filename,
                source_row_number=plan.clean_row_number,
                source_record_key=plan.record_key,
                target_column=plan.column,
                original_value=self._truncate(result.original_value),
                mutated_value=self._truncate(result.mutated_value),
                mutation_fingerprint=fingerprint,
                mutation_status=result.status,
                metadata_json={
                    **result.metadata,
                    "reason": plan.reason,
                    "messy_generator_version": self.settings.MESSY_GENERATOR_VERSION,
                },
            )
            session.add(record)
            records.append(record)
        session.flush()
        return records

    @staticmethod
    def _persist_expectations(
        session: Session,
        tenant_id: int,
        run_id: int,
        results: list[MutationResult],
        issues: list[ExpectedIssue],
        mutations: list[DataMutation],
    ) -> None:
        issue_index = 0
        for result, mutation in zip(results, mutations, strict=True):
            if result.status != "applied":
                continue
            issue = issues[issue_index]
            issue_index += 1
            session.add(
                ExpectedException(
                    tenant_id=tenant_id,
                    messy_dataset_run_id=run_id,
                    expected_exception_code=issue.code,
                    expected_issue_type=issue.issue_type,
                    expected_severity=issue.severity,
                    expected_file_type=issue.file_type,
                    expected_filename=issue.filename,
                    expected_source_row_number=issue.row_number,
                    expected_source_record_key=issue.record_key,
                    expected_column_name=issue.column,
                    related_mutation_id=mutation.id,
                    expected_message_pattern=issue.message_pattern,
                    expected_count_group=f"{issue.file_type}:{issue.code}",
                    expectation_fingerprint=issue.fingerprint,
                    status="expected",
                    metadata_json=issue.metadata,
                )
            )

    def _controls(
        self,
        session: Session,
        tenant_id: int,
        run_id: int,
        clean_files: list[GeneratedSourceFile],
        documents: dict[str, CsvDocument],
        results: list[MutationResult],
        issues: list[ExpectedIssue],
        clean_checksums: dict[str, str],
    ) -> list[MessyGenerationControlTotal]:
        applied = sum(item.status == "applied" for item in results)
        skipped = sum(item.status == "skipped" for item in results)
        failed = sum(item.status == "failed" for item in results)
        clean_rows = sum(item.record_count for item in clean_files)
        messy_rows = sum(len(item.rows) for item in documents.values())
        values = (
            ("clean_file_count_vs_messy_file_count", len(clean_files), len(documents), 0),
            ("clean_row_count_vs_messy_row_count", clean_rows, messy_rows, messy_rows - clean_rows),
            (
                "requested_defects_vs_applied_skipped_failed",
                len(results),
                applied + skipped + failed,
                0,
            ),
            ("applied_defects_vs_expected_exceptions", applied, len(issues), 0),
            ("clean_checksums_unchanged", len(clean_checksums), len(clean_checksums), 0),
            (
                "duplicate_row_count_delta",
                0,
                sum(
                    "duplicate" in item.plan.defect_type and item.status == "applied"
                    for item in results
                ),
                sum(
                    "duplicate" in item.plan.defect_type and item.status == "applied"
                    for item in results
                ),
            ),
            (
                "missing_identifier_count_delta",
                0,
                sum(
                    "missing" in item.plan.defect_type
                    and "identifier" in item.plan.defect_type
                    and item.status == "applied"
                    for item in results
                ),
                sum(
                    "missing" in item.plan.defect_type
                    and "identifier" in item.plan.defect_type
                    and item.status == "applied"
                    for item in results
                ),
            ),
            (
                "cross_file_relationship_break_count_delta",
                0,
                sum(
                    item.plan.defect_type
                    in {
                        "split_payment",
                        "combined_deposit",
                        "missing_payment",
                        "missing_ap_payment",
                        "missing_gl_entry",
                        "payroll_bank_withdrawal_mismatch",
                    }
                    and item.status == "applied"
                    for item in results
                ),
                sum(
                    item.plan.defect_type
                    in {
                        "split_payment",
                        "combined_deposit",
                        "missing_payment",
                        "missing_ap_payment",
                        "missing_gl_entry",
                        "payroll_bank_withdrawal_mismatch",
                    }
                    and item.status == "applied"
                    for item in results
                ),
            ),
        )
        controls: list[MessyGenerationControlTotal] = []
        for name, clean, messy, expected in values:
            difference = Decimal(messy) - Decimal(clean)
            control = MessyGenerationControlTotal(
                tenant_id=tenant_id,
                messy_dataset_run_id=run_id,
                control_name=name,
                clean_value=Decimal(clean),
                messy_value=Decimal(messy),
                difference_value=difference,
                expected_difference=Decimal(expected),
                tolerance=Decimal(0),
                status="matched" if difference == Decimal(expected) else "mismatch",
                metadata_json={},
            )
            session.add(control)
            controls.append(control)
        return controls

    def _verify_clean_unchanged(
        self, tenant: Tenant, clean_files: list[GeneratedSourceFile], original: dict[str, str]
    ) -> None:
        _, after = self._load_clean(tenant, clean_files)
        if after != original:
            raise MessyGenerationError("Clean generated files changed during messy generation")

    def _artifacts(
        self,
        session: Session,
        tenant: Tenant,
        run: MessyDatasetRun,
        scenario: DefectScenario,
        plan: list[dict[str, Any]],
        results: list[MutationResult],
        issues: list[ExpectedIssue],
        inventory: dict[str, str],
        controls: list[MessyGenerationControlTotal],
        output_fingerprint: str,
    ) -> None:
        key = output_fingerprint[:16]
        manifest_dir = (
            self.settings.MESSY_MANIFEST_ROOT.resolve() / tenant.code / f"run_{key}"
        ).resolve()
        report_dir = (
            self.settings.MESSY_REPORT_ROOT.resolve() / tenant.code / f"run_{key}"
        ).resolve()
        for root, path in (
            (self.settings.MESSY_MANIFEST_ROOT.resolve(), manifest_dir),
            (self.settings.MESSY_REPORT_ROOT.resolve(), report_dir),
        ):
            if root not in path.parents or path.exists():
                raise MessyGenerationError("Messy artifact path is invalid or already exists")
            path.mkdir(parents=True)
        mutations = [
            {
                "rule_code": item.plan.rule_code,
                "defect_type": item.plan.defect_type,
                "file": item.plan.filename,
                "row": item.plan.clean_row_number,
                "record_key": item.plan.record_key,
                "column": item.plan.column,
                "original_value": self._truncate(item.original_value),
                "mutated_value": self._truncate(item.mutated_value),
                "status": item.status,
                "metadata": item.metadata,
            }
            for item in results
        ]
        expected = [
            {
                "code": item.code,
                "issue_type": item.issue_type,
                "severity": item.severity,
                "file": item.filename,
                "row": item.row_number,
                "record_key": item.record_key,
                "column": item.column,
                "message_pattern": item.message_pattern,
                "fingerprint": item.fingerprint,
                "metadata": item.metadata,
            }
            for item in issues
        ]
        control_rows = [
            {
                "name": item.control_name,
                "clean": str(item.clean_value),
                "messy": str(item.messy_value),
                "difference": str(item.difference_value),
                "expected_difference": str(item.expected_difference),
                "status": item.status,
            }
            for item in controls
        ]
        clean_run = session.get(GeneratedDatasetRun, run.clean_generated_dataset_run_id)
        if clean_run is None:
            raise MessyGenerationError("Clean generated dataset disappeared")
        common = {
            "tenant_code": tenant.code,
            "clean_generated_dataset_key": clean_run.input_fingerprint,
            "messy_dataset_key": run.input_fingerprint,
            "messy_generator_version": run.messy_generator_version,
            "scenario_code": scenario.code,
            "scenario_version": scenario.version,
            "random_seed": run.random_seed,
            "input_fingerprint": run.input_fingerprint,
            "defect_plan_fingerprint": run.defect_plan_fingerprint,
            "output_fingerprint": output_fingerprint,
            "generated_messy_files": [
                {"filename": f"{name}.csv", "sha256": checksum}
                for name, checksum in sorted(inventory.items())
            ],
            "clean_file_integrity": "passed",
        }
        by_file: dict[str, int] = {}
        by_code: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for item in issues:
            by_file[item.filename] = by_file.get(item.filename, 0) + 1
            by_code[item.code] = by_code.get(item.code, 0) + 1
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
        artifacts = (
            (manifest_dir / "mutation_plan.json", {**common, "plan": plan}, "messy_mutation_plan"),
            (
                manifest_dir / "expected_exceptions.json",
                {
                    **common,
                    "total_expected": len(issues),
                    "counts_by_file": by_file,
                    "counts_by_issue_code": by_code,
                    "counts_by_severity": by_severity,
                    "row_level_expected_issues": expected,
                    "relationship_level_expected_issues": [
                        item
                        for item in expected
                        if item["issue_type"]
                        in {
                            "split_payment",
                            "combined_deposit",
                            "missing_payment",
                            "missing_ap_payment",
                            "missing_gl_entry",
                            "payroll_bank_withdrawal_mismatch",
                        }
                    ],
                    "generation_controls": control_rows,
                    "known_limitations": [
                        "Phase 7 creates expectations but does not detect or reconcile issues"
                    ],
                },
                "expected_exceptions_manifest",
            ),
            (
                manifest_dir / "mutation_manifest.json",
                {**common, "mutations": mutations},
                "mutation_manifest",
            ),
            (
                report_dir / "messy_file_inventory.json",
                {**common, "files": common["generated_messy_files"]},
                "messy_file_inventory",
            ),
            (
                report_dir / "messy_generation_summary.json",
                {
                    **common,
                    "requested": len(results),
                    "applied": sum(item.status == "applied" for item in results),
                    "skipped": sum(item.status == "skipped" for item in results),
                    "failed": sum(item.status == "failed" for item in results),
                    "expected_exceptions": len(issues),
                    "controls": control_rows,
                },
                "messy_generation_summary",
            ),
        )
        for path, payload, artifact_type in artifacts:
            content = _json_bytes(payload)
            path.write_bytes(content)
            root = self.settings.GENERATED_DATA_DIRECTORY.resolve()
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
                    metadata_json={"dataset_variant": "messy", "immutable": True},
                )
            )

    def verify(self, session: Session, tenant_id: int, run_id: int) -> dict[str, int]:
        run = session.scalar(
            select(MessyDatasetRun).where(
                MessyDatasetRun.id == run_id, MessyDatasetRun.tenant_id == tenant_id
            )
        )
        if run is None:
            raise MessyGenerationError("Messy dataset not found")
        tenant = session.get(Tenant, tenant_id)
        clean_run = session.get(GeneratedDatasetRun, run.clean_generated_dataset_run_id)
        if tenant is None or clean_run is None or clean_run.tenant_id != tenant_id:
            raise MessyGenerationError("Cross-tenant or missing clean dataset link")
        clean_files = list(
            session.scalars(
                select(GeneratedSourceFile)
                .where(GeneratedSourceFile.generated_dataset_run_id == clean_run.id)
                .order_by(GeneratedSourceFile.file_type)
            )
        )
        _, clean_inventory = self._load_clean(tenant, clean_files)
        if len(clean_files) != run.clean_file_count:
            raise MessyGenerationError("Clean file count differs from run summary")
        files = list(
            session.scalars(
                select(MessySourceFile)
                .where(MessySourceFile.messy_dataset_run_id == run.id)
                .order_by(MessySourceFile.file_type)
            )
        )
        if len(files) != run.messy_file_count or len(files) != len(clean_files):
            raise MessyGenerationError("Messy file count differs from run summary")
        root = self.settings.MESSY_GENERATED_ROOT.resolve()
        inventory: dict[str, str] = {}
        for item in files:
            try:
                relative = Path(item.relative_path).relative_to("generated/messy")
            except ValueError as error:
                raise MessyGenerationError("Invalid messy relative path") from error
            path = (root / relative).resolve()
            if (
                root not in path.parents
                or not path.is_file()
                or _sha(path.read_bytes()) != item.sha256_checksum
            ):
                raise MessyGenerationError(f"Messy checksum mismatch: {item.filename}")
            clean = session.get(GeneratedSourceFile, item.clean_generated_source_file_id)
            registered = session.get(SourceFile, item.source_file_id)
            if (
                clean is None
                or clean.tenant_id != tenant_id
                or clean.generated_dataset_run_id != clean_run.id
                or registered is None
                or registered.tenant_id != tenant_id
                or registered.sha256_checksum != item.sha256_checksum
            ):
                raise MessyGenerationError("Cross-tenant or missing clean file link")
            if clean_inventory.get(item.file_type) != clean.sha256_checksum:
                raise MessyGenerationError(f"Clean checksum mismatch: {clean.filename}")
            inventory[item.file_type] = item.sha256_checksum
        mutations = list(
            session.scalars(
                select(DataMutation)
                .where(DataMutation.messy_dataset_run_id == run.id)
                .order_by(DataMutation.id)
            )
        )
        expectations = list(
            session.scalars(
                select(ExpectedException)
                .where(ExpectedException.messy_dataset_run_id == run.id)
                .order_by(ExpectedException.id)
            )
        )
        applied = sum(item.mutation_status == "applied" for item in mutations)
        skipped = sum(item.mutation_status == "skipped" for item in mutations)
        failed = sum(item.mutation_status == "failed" for item in mutations)
        if (len(mutations), applied, skipped, failed, len(expectations)) != (
            run.requested_defect_count,
            run.applied_defect_count,
            run.skipped_defect_count,
            run.failed_defect_count,
            run.expected_exception_count,
        ):
            raise MessyGenerationError("Mutation counts differ from run summary")
        if applied != len(expectations):
            raise MessyGenerationError("Applied mutation and expectation counts differ")
        applied_ids = {item.id for item in mutations if item.mutation_status == "applied"}
        if any(item.related_mutation_id not in applied_ids for item in expectations):
            raise MessyGenerationError("Expected exception has an invalid mutation link")
        if len({item.mutation_fingerprint for item in mutations}) != len(mutations):
            raise MessyGenerationError("Duplicate mutation fingerprint")
        if len({item.expectation_fingerprint for item in expectations}) != len(expectations):
            raise MessyGenerationError("Duplicate expectation fingerprint")
        controls = list(
            session.scalars(
                select(MessyGenerationControlTotal).where(
                    MessyGenerationControlTotal.messy_dataset_run_id == run.id
                )
            )
        )
        if any(item.status != "matched" for item in controls):
            raise MessyGenerationError("Messy generation control mismatch")
        expected_output = _sha(
            _json_bytes(
                {
                    "files": inventory,
                    "expectations": [item.expectation_fingerprint for item in expectations],
                    "plan": run.defect_plan_fingerprint,
                }
            )
        )
        if expected_output != run.output_fingerprint:
            raise MessyGenerationError("Messy output fingerprint mismatch")
        artifacts = list(
            session.scalars(
                select(PipelineRunArtifact)
                .where(PipelineRunArtifact.pipeline_run_id == run.pipeline_run_id)
                .order_by(PipelineRunArtifact.id)
            )
        )
        if len(artifacts) != 5:
            raise MessyGenerationError("Messy artifact inventory is incomplete")
        artifact_root = self.settings.GENERATED_DATA_DIRECTORY.resolve()
        for artifact in artifacts:
            try:
                relative = Path(artifact.relative_path).relative_to("generated")
            except ValueError as error:
                raise MessyGenerationError("Invalid messy artifact relative path") from error
            path = (artifact_root / relative).resolve()
            if (
                artifact_root not in path.parents
                or not path.is_file()
                or _sha(path.read_bytes()) != artifact.checksum
            ):
                raise MessyGenerationError(f"Messy artifact checksum mismatch: {artifact.name}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("input_fingerprint") != run.input_fingerprint
                or payload.get("defect_plan_fingerprint") != run.defect_plan_fingerprint
                or payload.get("output_fingerprint") != run.output_fingerprint
            ):
                raise MessyGenerationError(f"Messy artifact metadata mismatch: {artifact.name}")
        return {
            "files": len(files),
            "mutations": len(mutations),
            "expectations": len(expectations),
            "controls": len(controls),
            "artifacts": len(artifacts),
        }
