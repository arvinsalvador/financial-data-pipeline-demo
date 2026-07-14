import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.models import (
    DataQualityIssue,
    IngestionControlTotal,
    PipelineDefinition,
    PipelineRun,
    PipelineRunArtifact,
    PipelineRunStep,
    RawSourceRow,
    RejectedSourceRow,
    SourceFile,
    SourceFileColumnProfile,
    SourceFileProfile,
    SourceSchemaMapping,
)
from app.services.checksum import calculate_sha256
from app.services.ingestion_connectors import BaseSourceConnector, RowError, connector_for
from app.services.ingestion_seed import mapping_matches_filename

INGESTION_STEPS = (
    "validate_tenant_and_permissions",
    "load_source_file_metadata",
    "verify_registered_file_checksum",
    "load_profile_and_mapping",
    "open_csv",
    "extract_raw_rows",
    "validate_and_parse_rows",
    "persist_accepted_staging_rows",
    "persist_rejected_rows",
    "calculate_control_totals",
    "validate_invariants",
    "register_artifacts",
    "finalize_ingestion",
)


class IngestionError(Exception):
    def __init__(self, message: str, *, run_id: int | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


@dataclass(frozen=True)
class IngestionResult:
    run: PipelineRun
    connector: str
    mapping_code: str
    mapping_version: str
    ingestion_version: str
    no_op: bool = False


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


class CsvIngestionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ingest(
        self,
        session: Session,
        source_file_id: int,
        tenant_id: int,
        mapping_code: str | None = None,
        *,
        force_rerun: bool = False,
    ) -> IngestionResult:
        source_file = session.scalar(
            select(SourceFile)
            .where(SourceFile.id == source_file_id, SourceFile.tenant_id == tenant_id)
            .options(selectinload(SourceFile.source_system))
        )
        if source_file is None:
            raise IngestionError("Source file not found")
        profile = session.scalar(
            select(SourceFileProfile)
            .where(
                SourceFileProfile.source_file_id == source_file.id,
                SourceFileProfile.tenant_id == tenant_id,
            )
            .order_by(SourceFileProfile.generated_at.desc())
            .limit(1)
        )
        if profile is None:
            raise IngestionError("A successful source-file profile is required")
        if profile.status not in {"completed", "completed_with_warnings"}:
            raise IngestionError("The latest source-file profile blocks ingestion")
        blocking = (
            session.scalar(
                select(func.count())
                .select_from(DataQualityIssue)
                .where(
                    DataQualityIssue.source_file_profile_id == profile.id,
                    DataQualityIssue.severity == "critical",
                    DataQualityIssue.status == "open",
                )
            )
            or 0
        )
        if blocking:
            raise IngestionError("The profile has an unresolved critical issue")
        mapping = self._mapping(session, tenant_id, source_file, mapping_code)
        prior = session.scalar(
            select(PipelineRun)
            .where(
                PipelineRun.tenant_id == tenant_id,
                PipelineRun.source_file_id == source_file.id,
                PipelineRun.run_type == "csv_ingestion",
                PipelineRun.status.in_(("completed", "completed_with_rejections")),
            )
            .order_by(PipelineRun.id.desc())
        )
        if (
            prior is not None
            and (prior.metadata_json or {}).get("ingestion_version")
            == self.settings.INGESTION_VERSION
            and (prior.metadata_json or {}).get("mapping_code") == mapping.mapping_code
        ):
            return IngestionResult(
                prior,
                str((prior.metadata_json or {}).get("connector", "")),
                mapping.mapping_code,
                mapping.mapping_version,
                self.settings.INGESTION_VERSION,
                no_op=True,
            )

        run = self._start_run(session, tenant_id, source_file.id, mapping, force_rerun)
        try:
            path = self._safe_registered_path(source_file)
            if not path.is_file():
                raise IngestionError("Registered physical file is unavailable", run_id=run.id)
            if calculate_sha256(path) != source_file.sha256_checksum:
                raise IngestionError("Registered file checksum does not match", run_id=run.id)
            self._complete_step(run, 1, {"tenant_id": tenant_id})
            self._complete_step(
                run,
                2,
                {
                    "source_file_id": source_file.id,
                    "source_system_code": source_file.source_system.code,
                },
            )
            self._complete_step(run, 3, {"sha256_checksum": source_file.sha256_checksum})
            headers = list(
                session.scalars(
                    select(SourceFileColumnProfile.column_name)
                    .where(SourceFileColumnProfile.source_file_profile_id == profile.id)
                    .order_by(SourceFileColumnProfile.column_position)
                ).all()
            )
            connector = connector_for(mapping, headers)
            run.metadata_json = {**(run.metadata_json or {}), "connector": connector.connector_name}
            self._complete_step(
                run,
                4,
                {
                    "profile_id": profile.id,
                    "mapping_id": mapping.id,
                    "mapping_code": mapping.mapping_code,
                    "mapping_version": mapping.mapping_version,
                    "bindings": connector.bindings,
                },
            )
            counts, source_total, accepted_total = self._process_rows(
                session, run, source_file, profile, mapping, connector, path
            )
            self._complete_step(
                run,
                10,
                {
                    "source_amount_total": str(source_total) if source_total is not None else None,
                    "accepted_amount_total": str(accepted_total)
                    if accepted_total is not None
                    else None,
                },
            )
            if counts[0] != counts[1] + counts[2]:
                raise IngestionError("Ingestion row-count invariant failed", run_id=run.id)
            self._complete_step(
                run, 11, {"invariant": "extracted = accepted + rejected", "valid": True}
            )
            run.records_extracted, run.records_accepted, run.records_rejected = counts
            controls = self._control_totals(
                session, run, source_file.id, counts, source_total, accepted_total
            )
            self._artifacts(session, run, source_file, mapping, connector, controls)
            self._complete_step(run, 12, {"artifact_count": 4})
            now = datetime.now(UTC)
            run.status = "completed_with_rejections" if counts[2] else "completed"
            run.completed_at = now
            self._complete_step(run, 13, {"status": run.status})
            session.commit()
            return IngestionResult(
                run,
                connector.connector_name,
                mapping.mapping_code,
                mapping.mapping_version,
                self.settings.INGESTION_VERSION,
            )
        except Exception as error:
            session.rollback()
            persisted = session.get(PipelineRun, run.id)
            if persisted is not None:
                persisted.status = "failed"
                persisted.completed_at = datetime.now(UTC)
                persisted.error_message = str(error)[:2000]
                current = next((step for step in persisted.steps if step.status == "running"), None)
                if current is None:
                    current = next(
                        (step for step in persisted.steps if step.status == "pending"), None
                    )
                if current is not None:
                    current.status = "failed"
                    current.completed_at = datetime.now(UTC)
                    current.error_message = str(error)[:2000]
                session.commit()
            if isinstance(error, IngestionError):
                error.run_id = run.id
                raise
            raise IngestionError(str(error), run_id=run.id) from error

    def _mapping(
        self, session: Session, tenant_id: int, source_file: SourceFile, mapping_code: str | None
    ) -> SourceSchemaMapping:
        query = (
            select(SourceSchemaMapping)
            .where(
                SourceSchemaMapping.tenant_id == tenant_id, SourceSchemaMapping.is_active.is_(True)
            )
            .options(selectinload(SourceSchemaMapping.columns))
        )
        if mapping_code:
            query = query.where(SourceSchemaMapping.mapping_code == mapping_code)
        candidates = list(session.scalars(query).all())
        candidates = [
            item
            for item in candidates
            if mapping_matches_filename(item, source_file.original_filename)
        ]
        if len(candidates) != 1:
            raise IngestionError("Exactly one active schema mapping must match the source file")
        mapping = candidates[0]
        if (
            mapping.source_system_id is not None
            and mapping.source_system_id != source_file.source_system_id
        ):
            raise IngestionError("Schema mapping belongs to another source system")
        return mapping

    def _start_run(
        self,
        session: Session,
        tenant_id: int,
        source_file_id: int,
        mapping: SourceSchemaMapping,
        force_rerun: bool,
    ) -> PipelineRun:
        definition = session.scalar(
            select(PipelineDefinition).where(
                PipelineDefinition.code == "csv_ingestion",
                PipelineDefinition.version == self.settings.INGESTION_VERSION,
                PipelineDefinition.is_active.is_(True),
            )
        )
        if definition is None:
            raise IngestionError("CSV ingestion pipeline definition is not active")
        now = datetime.now(UTC)
        run = PipelineRun(
            tenant_id=tenant_id,
            pipeline_definition_id=definition.id,
            run_type="csv_ingestion",
            status="running",
            started_at=now,
            source_file_id=source_file_id,
            metadata_json={
                "ingestion_version": self.settings.INGESTION_VERSION,
                "mapping_code": mapping.mapping_code,
                "mapping_version": mapping.mapping_version,
                "force_rerun": force_rerun,
            },
        )
        for order, name in enumerate(INGESTION_STEPS, 1):
            run.steps.append(
                PipelineRunStep(
                    step_name=name,
                    step_order=order,
                    status="running" if order == 1 else "pending",
                    started_at=now,
                    metadata_json={},
                )
            )
        session.add(run)
        session.commit()
        return run

    def _safe_registered_path(self, source_file: SourceFile) -> Path:
        root = self.settings.REGISTERED_RAW_DIRECTORY.resolve()
        path = (root / source_file.stored_filename).resolve()
        if path.parent != root:
            raise IngestionError("Registered source path is invalid")
        return path

    def _complete_step(self, run: PipelineRun, order: int, metadata: dict[str, Any]) -> None:
        step = run.steps[order - 1]
        step.status = "completed"
        step.completed_at = datetime.now(UTC)
        step.metadata_json = metadata
        if order < len(run.steps):
            run.steps[order].status = "running"

    def _process_rows(
        self,
        session: Session,
        run: PipelineRun,
        source_file: SourceFile,
        profile: SourceFileProfile,
        mapping: SourceSchemaMapping,
        connector: BaseSourceConnector,
        path: Path,
    ) -> tuple[tuple[int, int, int], Decimal | None, Decimal | None]:
        extracted = accepted = rejected = 0
        source_total: Decimal | None = None
        accepted_total: Decimal | None = None
        seen_hashes: set[str] = set()
        seen_ids: set[str] = set()
        with path.open("r", encoding=profile.encoding or "utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=profile.delimiter or ",")
            actual_headers = next(reader, None)
            if actual_headers is None:
                raise IngestionError("Registered CSV has no header", run_id=run.id)
            expected_headers = [column.strip() for column in actual_headers]
            if expected_headers != list(connector.bindings.values()) and set(
                expected_headers
            ) != set(
                session.scalars(
                    select(SourceFileColumnProfile.column_name).where(
                        SourceFileColumnProfile.source_file_profile_id == profile.id
                    )
                ).all()
            ):
                raise IngestionError(
                    "CSV headers no longer match the successful profile", run_id=run.id
                )
            self._complete_step(
                run, 5, {"encoding": profile.encoding, "delimiter": profile.delimiter}
            )
            for row_number, values in enumerate(reader, start=2):
                if not values or all(not value.strip() for value in values):
                    continue
                extracted += 1
                errors: list[RowError] = []
                if len(values) != len(expected_headers):
                    errors.append(
                        RowError(
                            "invalid_row_structure",
                            "schema",
                            None,
                            str(len(values)),
                            f"Expected {len(expected_headers)} columns but found {len(values)}",
                        )
                    )
                raw_data = {
                    header: values[index] if index < len(values) else None
                    for index, header in enumerate(expected_headers)
                }
                if len(values) > len(expected_headers):
                    raw_data["_extra_fields"] = json.dumps(
                        values[len(expected_headers) :], ensure_ascii=False
                    )
                row_hash = hashlib.sha256(
                    json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
                ).hexdigest()
                if row_hash in seen_hashes:
                    errors.append(
                        RowError(
                            "duplicate_raw_row",
                            "duplicate",
                            None,
                            row_hash[:12],
                            "The same raw row occurs more than once in this file",
                        )
                    )
                seen_hashes.add(row_hash)
                parsed = connector.parse(raw_data)
                errors.extend(parsed.errors)
                source_record_id = parsed.values.get("source_record_id")
                if isinstance(source_record_id, str) and source_record_id:
                    if source_record_id in seen_ids:
                        errors.append(
                            RowError(
                                "duplicate_source_identifier",
                                "duplicate",
                                "source_record_id",
                                source_record_id,
                                "The source identifier occurs more than once in this file",
                            )
                        )
                    seen_ids.add(source_record_id)
                row = RawSourceRow(
                    tenant_id=run.tenant_id,
                    source_system_id=source_file.source_system_id,
                    source_file_id=source_file.id,
                    pipeline_run_id=run.id,
                    source_row_number=row_number,
                    source_record_id=source_record_id,
                    raw_data_json=raw_data,
                    raw_row_hash=row_hash,
                    ingestion_version=self.settings.INGESTION_VERSION,
                    row_status="rejected" if errors else "accepted",
                )
                session.add(row)
                session.flush()
                amount = connector.monetary_total(parsed.values)
                if amount is not None:
                    source_total = (source_total or Decimal(0)) + amount
                if errors:
                    rejected += 1
                    for issue in errors:
                        identity = (
                            f"{source_file.id}|{row_number}|{self.settings.INGESTION_VERSION}|"
                            f"{issue.code}|{issue.field or ''}"
                        )
                        fingerprint = hashlib.sha256(identity.encode()).hexdigest()
                        session.add(
                            RejectedSourceRow(
                                tenant_id=run.tenant_id,
                                source_system_id=source_file.source_system_id,
                                source_file_id=source_file.id,
                                pipeline_run_id=run.id,
                                raw_source_row_id=row.id,
                                source_row_number=row_number,
                                rejection_code=issue.code,
                                rejection_category=issue.category,
                                severity=issue.severity,
                                field_name=issue.field,
                                observed_value=(issue.observed[:500] if issue.observed else None),
                                message=issue.message,
                                rejection_fingerprint=fingerprint,
                                metadata_json={
                                    "ingestion_version": self.settings.INGESTION_VERSION,
                                    "mapping_code": mapping.mapping_code,
                                },
                            )
                        )
                else:
                    common = {
                        "tenant_id": run.tenant_id,
                        "source_system_id": source_file.source_system_id,
                        "source_file_id": source_file.id,
                        "pipeline_run_id": run.id,
                        "raw_source_row_id": row.id,
                        "source_row_number": row_number,
                        "source_record_id": source_record_id,
                        "ingestion_version": self.settings.INGESTION_VERSION,
                        "row_hash": row_hash,
                    }
                    session.add(connector.build(common, parsed.values))
                    accepted += 1
                    if amount is not None:
                        accepted_total = (accepted_total or Decimal(0)) + amount
        self._complete_step(
            run,
            6,
            {
                "extracted": extracted,
                "row_number_convention": "physical CSV line; header is line 1",
            },
        )
        self._complete_step(run, 7, {"accepted": accepted, "rejected": rejected})
        self._complete_step(
            run, 8, {"accepted": accepted, "target_record_type": mapping.target_record_type}
        )
        self._complete_step(run, 9, {"rejected_rows": rejected})
        return (extracted, accepted, rejected), source_total, accepted_total

    def _control_totals(
        self,
        session: Session,
        run: PipelineRun,
        source_file_id: int,
        counts: tuple[int, int, int],
        source_total: Decimal | None,
        accepted_total: Decimal | None,
    ) -> list[IngestionControlTotal]:
        controls: list[IngestionControlTotal] = []
        values = (
            ("extracted_row_count", Decimal(counts[0]), Decimal(counts[1] + counts[2])),
            ("accepted_row_count", Decimal(counts[1]), Decimal(counts[1])),
            ("rejected_row_count", Decimal(counts[2]), Decimal(counts[2])),
            ("source_amount_total", source_total, accepted_total),
        )
        for name, source, loaded in values:
            difference = loaded - source if source is not None and loaded is not None else None
            status = (
                "unavailable"
                if difference is None
                else ("matched" if difference == 0 else "mismatch")
            )
            control = IngestionControlTotal(
                tenant_id=run.tenant_id,
                source_file_id=source_file_id,
                pipeline_run_id=run.id,
                control_name=name,
                source_value=source,
                loaded_value=loaded,
                difference_value=difference,
                tolerance=Decimal("0.000001"),
                status=status,
                metadata_json={
                    "basis": "parsed source rows; rejected monetary values excluded when unparsable"
                },
            )
            session.add(control)
            controls.append(control)
        session.flush()
        return controls

    def _artifacts(
        self,
        session: Session,
        run: PipelineRun,
        source_file: SourceFile,
        mapping: SourceSchemaMapping,
        connector: BaseSourceConnector,
        controls: list[IngestionControlTotal],
    ) -> None:
        payloads = {
            "ingestion_manifest": {
                "tenant_id": run.tenant_id,
                "source_system_code": source_file.source_system.code,
                "source_file_id": source_file.id,
                "source_checksum": source_file.sha256_checksum,
                "pipeline_run_id": run.id,
                "connector": connector.connector_name,
                "mapping_code": mapping.mapping_code,
                "mapping_version": mapping.mapping_version,
                "ingestion_version": self.settings.INGESTION_VERSION,
                "extracted_count": run.records_extracted,
                "accepted_count": run.records_accepted,
                "rejected_count": run.records_rejected,
                "run_status": (
                    "completed_with_rejections" if run.records_rejected else "completed"
                ),
                "started_at": run.started_at,
                "generated_at": datetime.now(UTC),
            },
            "rejected_row_report": {
                "pipeline_run_id": run.id,
                "rejected_count": run.records_rejected,
                "rejections": [
                    {
                        "row": item.source_row_number,
                        "code": item.rejection_code,
                        "category": item.rejection_category,
                        "field": item.field_name,
                        "message": item.message,
                        "severity": item.severity,
                    }
                    for item in session.scalars(
                        select(RejectedSourceRow).where(RejectedSourceRow.pipeline_run_id == run.id)
                    ).all()
                ],
            },
            "control_total_report": {
                "pipeline_run_id": run.id,
                "controls": [
                    {
                        "name": item.control_name,
                        "source": item.source_value,
                        "loaded": item.loaded_value,
                        "difference": item.difference_value,
                        "status": item.status,
                    }
                    for item in controls
                ],
            },
            "ingestion_summary": {
                "pipeline_run_id": run.id,
                "extracted": run.records_extracted,
                "accepted": run.records_accepted,
                "rejected": run.records_rejected,
            },
        }
        roots = {
            "ingestion_manifest": (
                self.settings.MANIFESTS_DIRECTORY / "ingestion",
                "manifests/ingestion",
            ),
            "rejected_row_report": (
                self.settings.INGESTION_REPORTS_DIRECTORY / "rejections",
                "reports/rejections",
            ),
            "control_total_report": (
                self.settings.INGESTION_REPORTS_DIRECTORY / "control-totals",
                "reports/control-totals",
            ),
            "ingestion_summary": (
                self.settings.INGESTION_REPORTS_DIRECTORY / "ingestion",
                "reports/ingestion",
            ),
        }
        for artifact_type, payload in payloads.items():
            directory, relative_root = roots[artifact_type]
            directory.mkdir(parents=True, exist_ok=True)
            filename = f"run_{run.id}_{artifact_type}.json"
            path = directory / filename
            encoded = json.dumps(
                payload, default=_json_default, ensure_ascii=False, indent=2
            ).encode()
            with path.open("xb") as handle:
                handle.write(encoded)
            session.add(
                PipelineRunArtifact(
                    tenant_id=run.tenant_id,
                    pipeline_run_id=run.id,
                    artifact_type=artifact_type,
                    name=filename,
                    relative_path=f"{relative_root}/{filename}",
                    checksum=hashlib.sha256(encoded).hexdigest(),
                    mime_type="application/json",
                    file_size_bytes=len(encoded),
                    metadata_json={"ingestion_version": self.settings.INGESTION_VERSION},
                )
            )
