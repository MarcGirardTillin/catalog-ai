"""Ephemeral disk staging for processed/generated images.

Files live under ``settings.IMAGING_DIR`` as ``{asset_id}/{stem}.{fmt}`` —
stems are output indexes ("0", "1", …) or roles ("cutout", "source") — and
are purged after save, plus a retention sweep at startup (90 jours : les
visuels écartés restent consultables un temps — trace de ce qui a été payé —
sans transformer le disque du serveur en politique par défaut).
Paths handed back to callers are always staging-relative; ``load`` refuses
anything that resolves outside the staging root (path traversal).
"""

import logging
import time
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# Rétention des fichiers stagés non sauvegardés (jours).
RETENTION_DAYS = 90


def _base_dir() -> Path:
    return Path(settings.IMAGING_DIR)


def store(asset_id: int, stem: int | str, data: bytes, fmt: str) -> str:
    """Write one staged file; returns its staging-relative path."""
    extension = fmt.lstrip(".").lower() or "bin"
    directory = _base_dir() / str(asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.{extension}"
    path.write_bytes(data)
    return f"{asset_id}/{stem}.{extension}"


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


def sweep_older_than(days: int = RETENTION_DAYS) -> int:
    """Purge les dossiers d'assets plus vieux que ``days`` (mtime).

    Appelé au démarrage de l'app — assez pour un serveur redéployé
    régulièrement. Retourne le nombre de dossiers purgés.
    """
    base = _base_dir()
    if not base.is_dir():
        return 0
    cutoff = time.time() - days * 86_400
    purged = 0
    for directory in base.iterdir():
        if not directory.is_dir():
            continue
        try:
            newest = max(
                (child.stat().st_mtime for child in directory.iterdir()),
                default=directory.stat().st_mtime,
            )
            if newest < cutoff:
                for child in directory.iterdir():
                    child.unlink(missing_ok=True)
                directory.rmdir()
                purged += 1
        except OSError as exc:  # fichier verrouillé, course… : on passera
            logger.warning("staging sweep skipped %s: %s", directory, exc)
    if purged:
        logger.info("staging sweep: %d asset directories purged", purged)
    return purged


def purge_asset(asset_id: int) -> None:
    """Remove every staged file of one asset (idempotent)."""
    directory = _base_dir() / str(asset_id)
    if not directory.is_dir():
        return
    for child in directory.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
    directory.rmdir()
