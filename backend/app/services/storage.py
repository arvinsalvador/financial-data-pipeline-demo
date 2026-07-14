import os
import tempfile
from pathlib import Path

from app.core.config import Settings
from app.exceptions import StorageCollision, StorageFailure


class ImmutableStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_directories(self) -> None:
        for directory in (
            self.settings.UPLOAD_TEMP_DIRECTORY,
            self.settings.REGISTERED_RAW_DIRECTORY,
            self.settings.REJECTED_RAW_DIRECTORY,
            self.settings.MANIFESTS_DIRECTORY,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def create_temporary_file(self) -> Path:
        self.ensure_directories()
        descriptor, path = tempfile.mkstemp(
            prefix="upload_", suffix=".tmp", dir=self.settings.UPLOAD_TEMP_DIRECTORY
        )
        os.close(descriptor)
        return Path(path)

    def register(self, temporary_path: Path, stored_filename: str) -> Path:
        target = self.settings.REGISTERED_RAW_DIRECTORY / stored_filename
        try:
            os.link(temporary_path, target)
            target.chmod(0o444)
            temporary_path.unlink()
        except FileExistsError as error:
            raise StorageCollision(
                "A registered file already exists at the target path."
            ) from error
        except OSError as error:
            raise StorageFailure(
                "The uploaded file could not be moved to immutable storage."
            ) from error
        return target

    @staticmethod
    def remove_if_present(path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return
