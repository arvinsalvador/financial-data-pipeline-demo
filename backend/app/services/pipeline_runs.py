from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PipelineRun, PipelineRunStep


class PipelineRunRecorder:
    step_name = "receive_and_register"

    def start(self, session: Session, original_filename: str, source_system_code: str) -> int:
        now = datetime.now(UTC)
        run = PipelineRun(run_type="source_file_upload", status="running", started_at=now)
        run.steps.append(
            PipelineRunStep(
                step_name=self.step_name,
                step_order=1,
                status="running",
                started_at=now,
                metadata_json={
                    "original_filename": original_filename,
                    "source_system_code": source_system_code,
                },
            )
        )
        session.add(run)
        session.commit()
        return run.id

    def complete(
        self,
        session: Session,
        run_id: int,
        source_file_id: int,
        metadata: dict[str, Any],
    ) -> None:
        run, step = self._load(session, run_id)
        now = datetime.now(UTC)
        run.status = "registered"
        run.source_file_id = source_file_id
        run.completed_at = now
        step.status = "registered"
        step.completed_at = now
        step.metadata_json = {**(step.metadata_json or {}), **metadata}
        session.commit()

    def duplicate(self, session: Session, run_id: int, source_file_id: int, checksum: str) -> None:
        run, step = self._load(session, run_id)
        now = datetime.now(UTC)
        run.status = "duplicate"
        run.source_file_id = source_file_id
        run.completed_at = now
        step.status = "duplicate"
        step.completed_at = now
        step.metadata_json = {**(step.metadata_json or {}), "sha256_checksum": checksum}
        session.commit()

    def fail(self, session: Session, run_id: int, message: str) -> None:
        session.rollback()
        run, step = self._load(session, run_id)
        now = datetime.now(UTC)
        run.status = "failed"
        run.completed_at = now
        run.error_message = message
        step.status = "failed"
        step.completed_at = now
        step.error_message = message
        session.commit()

    @staticmethod
    def _load(session: Session, run_id: int) -> tuple[PipelineRun, PipelineRunStep]:
        run = session.get(PipelineRun, run_id)
        step = session.scalar(
            select(PipelineRunStep).where(PipelineRunStep.pipeline_run_id == run_id)
        )
        if run is None or step is None:
            raise RuntimeError(f"Pipeline run {run_id} is missing its audit step")
        return run, step
