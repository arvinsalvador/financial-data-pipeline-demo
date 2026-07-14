class UploadServiceError(Exception):
    code = "upload_failure"
    status_code = 500

    def __init__(self, message: str, *, pipeline_run_id: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.pipeline_run_id = pipeline_run_id


class UnsupportedExtension(UploadServiceError):
    code = "unsupported_extension"
    status_code = 415


class InvalidMimeType(UploadServiceError):
    code = "invalid_mime_type"
    status_code = 415


class FileTooLarge(UploadServiceError):
    code = "file_too_large"
    status_code = 413


class MissingSourceSystem(UploadServiceError):
    code = "missing_source_system"
    status_code = 404


class DuplicateSourceFile(UploadServiceError):
    code = "duplicate"
    status_code = 200

    def __init__(
        self,
        existing_source_file_id: int,
        sha256_checksum: str,
        *,
        pipeline_run_id: int,
    ) -> None:
        super().__init__(
            "This exact file has already been registered.", pipeline_run_id=pipeline_run_id
        )
        self.existing_source_file_id = existing_source_file_id
        self.sha256_checksum = sha256_checksum


class InvalidFilename(UploadServiceError):
    code = "invalid_filename"
    status_code = 400


class StorageCollision(UploadServiceError):
    code = "storage_collision"
    status_code = 409


class StorageFailure(UploadServiceError):
    code = "storage_failure"
    status_code = 500


class RegistrationFailure(UploadServiceError):
    code = "registration_failure"
    status_code = 500
