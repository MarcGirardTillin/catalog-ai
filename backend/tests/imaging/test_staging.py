"""Tests for the ephemeral imaging staging (store/load/purge + traversal)."""

from pathlib import Path

import pytest

from app.core.config import settings
from app.imaging import staging


@pytest.fixture(autouse=True)
def _staging_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "imaging"
    monkeypatch.setattr(settings, "IMAGING_DIR", str(directory))
    return directory


def test_store_then_load_roundtrip(_staging_dir: Path) -> None:
    relpath = staging.store(7, 0, b"webp-bytes", "webp")

    assert relpath == "7/0.webp"
    assert (_staging_dir / "7" / "0.webp").is_file()
    assert staging.load(relpath) == b"webp-bytes"


def test_load_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        staging.load("7/0.webp")


def test_load_rejects_path_traversal(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"secret")

    with pytest.raises(ValueError):
        staging.load("../secret.txt")


def test_purge_asset_removes_files_and_is_idempotent(_staging_dir: Path) -> None:
    staging.store(7, 0, b"a", "webp")
    staging.store(7, 1, b"b", "webp")
    staging.store(8, 0, b"c", "jpeg")

    staging.purge_asset(7)

    assert not (_staging_dir / "7").exists()
    assert staging.load("8/0.jpeg") == b"c"  # other assets untouched
    staging.purge_asset(7)  # second purge is a no-op
