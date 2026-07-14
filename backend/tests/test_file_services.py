from pathlib import Path

import pytest

from app.core.config import Settings
from app.exceptions import InvalidFilename, StorageCollision
from app.services.checksum import calculate_sha256
from app.services.filename import deterministic_stored_filename, sanitize_filename
from app.services.storage import ImmutableStorage


def test_checksum_generation(tmp_path: Path) -> None:
    source = tmp_path / "sample.csv"
    source.write_bytes(b"date,amount\n2026-01-01,10.00\n")

    assert (
        calculate_sha256(source)
        == "533c29bb8802c3bb27a313a1741941cc55bf0a763e190d5efe8de19eb9e8994e"
    )


def test_filename_sanitization() -> None:
    assert sanitize_filename("Checking Account (Main).csv") == "Checking_Account_Main_.csv"


@pytest.mark.parametrize("filename", ["../escape.csv", "folder/file.csv", "folder\\file.csv"])
def test_path_traversal_is_rejected(filename: str) -> None:
    with pytest.raises(InvalidFilename):
        sanitize_filename(filename)


def test_deterministic_filename_generation() -> None:
    checksum = "a" * 64
    assert deterministic_stored_filename(checksum, "checking.csv") == f"{checksum}_checking.csv"


def test_registered_file_is_not_overwritten(test_settings: Settings) -> None:
    storage = ImmutableStorage(test_settings)
    first = storage.create_temporary_file()
    first.write_bytes(b"original")
    target = storage.register(first, "fixed.csv")
    second = storage.create_temporary_file()
    second.write_bytes(b"replacement")

    with pytest.raises(StorageCollision):
        storage.register(second, "fixed.csv")

    assert target.read_bytes() == b"original"
