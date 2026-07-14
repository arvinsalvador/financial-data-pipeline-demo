from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.exceptions import (
    DuplicateSourceFile,
    FileTooLarge,
    MissingSourceSystem,
    RegistrationFailure,
    UploadServiceError,
)
from app.models import SourceFile, SourceSystem
from app.services.checksum import StreamingChecksum
from app.services.filename import deterministic_stored_filename, sanitize_filename
from app.services.pipeline_runs import PipelineRunRecorder
from app.services.storage import ImmutableStorage
from app.services.validation import validate_file_type

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class RegistrationResult:
    source_file: SourceFile
    pipeline_run_id: int


class SourceFileRegistrationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = ImmutableStorage(settings)
        self.recorder = PipelineRunRecorder()

    async def register(
        self, session: Session, upload: UploadFile, source_system_code: str
    ) -> RegistrationResult:
        original_filename = upload.filename or ""
        run_id = self.recorder.start(session, original_filename, source_system_code)
        temporary_path: Path | None = None
        registered_path: Path | None = None
        try:
            source_system = session.scalar(
                select(SourceSystem).where(
                    SourceSystem.code == source_system_code, SourceSystem.is_active.is_(True)
                )
            )
            if source_system is None:
                raise MissingSourceSystem(
                    "The selected source system does not exist or is inactive."
                )

            sanitized_filename = sanitize_filename(original_filename)
            extension, mime_type = validate_file_type(
                sanitized_filename, upload.content_type, self.settings
            )
            temporary_path, file_size, checksum = await self._stream_to_temporary(upload)

            existing = session.scalar(
                select(SourceFile).where(SourceFile.sha256_checksum == checksum)
            )
            if existing is not None:
                self.storage.remove_if_present(temporary_path)
                self.recorder.duplicate(session, run_id, existing.id, checksum)
                raise DuplicateSourceFile(existing.id, checksum, pipeline_run_id=run_id)

            stored_filename = deterministic_stored_filename(checksum, sanitized_filename)
            registered_path = self.storage.register(temporary_path, stored_filename)
            temporary_path = None
            now = datetime.now(UTC)
            source_file = SourceFile(
                source_system_id=source_system.id,
                original_filename=original_filename,
                stored_filename=stored_filename,
                relative_path=f"raw/registered/{stored_filename}",
                file_extension=extension,
                mime_type=mime_type,
                file_size_bytes=file_size,
                sha256_checksum=checksum,
                status="registered",
                discovered_at=now,
                registered_at=now,
            )
            session.add(source_file)
            session.flush()
            source_file_id = source_file.id
            self.recorder.complete(
                session,
                run_id,
                source_file_id,
                {
                    "stored_filename": stored_filename,
                    "sha256_checksum": checksum,
                    "file_size_bytes": file_size,
                },
            )
            session.refresh(source_file)
            return RegistrationResult(source_file=source_file, pipeline_run_id=run_id)
        except DuplicateSourceFile:
            raise
        except UploadServiceError as error:
            self.storage.remove_if_present(temporary_path)
            self.recorder.fail(session, run_id, error.message)
            error.pipeline_run_id = run_id
            raise
        except SQLAlchemyError as error:
            self.storage.remove_if_present(temporary_path)
            self.storage.remove_if_present(registered_path)
            failure = RegistrationFailure(
                "The source file could not be registered.", pipeline_run_id=run_id
            )
            self.recorder.fail(session, run_id, failure.message)
            raise failure from error

    async def _stream_to_temporary(self, upload: UploadFile) -> tuple[Path, int, str]:
        temporary_path = self.storage.create_temporary_file()
        checksum = StreamingChecksum()
        file_size = 0
        try:
            with temporary_path.open("wb") as file_handle:
                while chunk := await upload.read(CHUNK_SIZE):
                    file_size += len(chunk)
                    if file_size > self.settings.MAX_UPLOAD_SIZE_BYTES:
                        maximum_size = self.settings.MAX_UPLOAD_SIZE_BYTES
                        raise FileTooLarge(f"The file exceeds the {maximum_size}-byte limit.")
                    checksum.update(chunk)
                    file_handle.write(chunk)
        except Exception:
            self.storage.remove_if_present(temporary_path)
            raise
        finally:
            await upload.close()
        return temporary_path, file_size, checksum.hexdigest()
