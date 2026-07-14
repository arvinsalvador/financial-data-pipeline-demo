from pathlib import Path

from app.core.config import Settings
from app.exceptions import InvalidMimeType, UnsupportedExtension


def validate_file_type(
    sanitized_filename: str, mime_type: str | None, settings: Settings
) -> tuple[str, str]:
    extension = Path(sanitized_filename).suffix.lower()
    if extension not in settings.allowed_source_file_extensions:
        raise UnsupportedExtension(
            f"Only {', '.join(sorted(settings.allowed_source_file_extensions))} files are allowed."
        )

    normalized_mime_type = (mime_type or "application/octet-stream").split(";", 1)[0].lower()
    if normalized_mime_type not in settings.allowed_source_file_mime_types:
        raise InvalidMimeType(f"MIME type '{normalized_mime_type}' is not allowed.")
    return extension, normalized_mime_type
