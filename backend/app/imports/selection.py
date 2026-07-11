"""Stored source files of an import job (``selection_json``).

An import job stores its uploaded source files under ``selection_json``. The
current shape is ``{"files": [{"file_name": original, "file_path": stored},
...]}`` (a list — an import can cross several documents of the same purchase
order). The legacy mono shape ``{"file_name": str, "file_path": str}`` is still
read: :func:`stored_import_files` always normalizes to a list, so every reader
(runner, download/preview, products view, ``_to_public``) stays agnostic.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import EnrichmentJob


def stored_import_files(job: "EnrichmentJob") -> list[dict[str, str]]:
    """Return the job's stored source files as ``[{file_name, file_path}, ...]``.

    Normalizes both the current ``selection_json["files"]`` list and the legacy
    ``{"file_name", "file_path"}`` mono shape to a single list. Entries are
    always ``{"file_name": str, "file_path": str}`` (missing values become "").
    """
    selection = job.selection_json or {}
    raw = selection.get("files")
    entries: list[dict[str, Any]]
    if isinstance(raw, list):
        entries = [f for f in raw if isinstance(f, dict)]
    elif selection.get("file_path") or selection.get("file_name"):
        entries = [selection]
    else:
        entries = []
    return [
        {
            "file_name": str(entry.get("file_name") or ""),
            "file_path": str(entry.get("file_path") or ""),
        }
        for entry in entries
    ]
