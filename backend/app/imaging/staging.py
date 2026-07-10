"""Ephemeral disk staging for processed/generated images.

Files live under ``settings.IMAGING_DIR`` as ``{asset_id}/{index}.{fmt}`` and
are purged after save (or by a simple TTL sweep later). Paths handed back to
callers are always staging-relative; ``load`` refuses anything that resolves
outside the staging root (path traversal).
"""

from pathlib import Path

from app.core.config import settings


def _base_dir() -> Path:
    return Path(settings.IMAGING_DIR)


def store(asset_id: int, index: int, data: bytes, fmt: str) -> str:
    """Write one produced image; returns its staging-relative path."""
    extension = fmt.lstrip(".").lower() or "bin"
    directory = _base_dir() / str(asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{index}.{extension}"
    path.write_bytes(data)
    return f"{asset_id}/{index}.{extension}"


def load(relpath: str) -> bytes:
    """Read one staged file by its relative path.

    Raises FileNotFoundError when absent, ValueError when the path escapes the
    staging root (hostile/corrupted relpath).
    """
    base = _base_dir().resolve()
    path = (base / relpath).resolve()
    if base != path and base not in path.parents:
        raise ValueError(f"staged path escapes the staging root: {relpath!r}")
    if not path.is_file():
        raise FileNotFoundError(relpath)
    return path.read_bytes()


def purge_asset(asset_id: int) -> None:
    """Remove every staged file of one asset (idempotent)."""
    directory = _base_dir() / str(asset_id)
    if not directory.is_dir():
        return
    for child in directory.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
    directory.rmdir()
