import re
import unicodedata
from pathlib import Path

from app.exceptions import InvalidFilename

UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")
REPEATED_UNDERSCORES = re.compile(r"_+")


def sanitize_filename(original_filename: str) -> str:
    candidate = original_filename.strip()
    if (
        not candidate
        or len(candidate) > 255
        or "\x00" in candidate
        or "/" in candidate
        or "\\" in candidate
        or candidate in {".", ".."}
        or Path(candidate).name != candidate
    ):
        raise InvalidFilename("The uploaded filename is invalid or contains a path.")

    normalized = unicodedata.normalize("NFKD", candidate).encode("ascii", "ignore").decode()
    sanitized = REPEATED_UNDERSCORES.sub("_", UNSAFE_CHARACTERS.sub("_", normalized)).strip("._")
    if not sanitized or sanitized in {".", ".."}:
        raise InvalidFilename("The uploaded filename does not contain a usable name.")

    if len(sanitized) > 180:
        suffix = Path(sanitized).suffix
        sanitized = f"{Path(sanitized).stem[: 180 - len(suffix)]}{suffix}"
    return sanitized


def deterministic_stored_filename(sha256_checksum: str, sanitized_filename: str) -> str:
    return f"{sha256_checksum}_{sanitized_filename}"
