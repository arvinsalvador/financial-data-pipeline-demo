import hashlib
from pathlib import Path


class StreamingChecksum:
    def __init__(self) -> None:
        self._hasher = hashlib.sha256()

    def update(self, chunk: bytes) -> None:
        self._hasher.update(chunk)

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


def calculate_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    checksum = StreamingChecksum()
    with path.open("rb") as file_handle:
        while chunk := file_handle.read(chunk_size):
            checksum.update(chunk)
    return checksum.hexdigest()
