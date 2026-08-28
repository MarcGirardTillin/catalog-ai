"""Avertissement « référence déjà présente dans Tillin » (posé sur un item).

Partagé entre le staging (runner d'import) et l'édition en review (PATCH
item) : quand la référence change, le contrôle est rejoué et l'ancien
avertissement remplacé — jamais empilé.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

EXISTING_REFERENCE_PREFIX = "Référence déjà présente dans Tillin"


def existing_reference_warning(existing: Mapping[str, Any]) -> str:
    title = str(existing.get("title") or "").strip()
    return (
        EXISTING_REFERENCE_PREFIX
        + (f" (« {title} »" if title else " (")
        + f" produit #{existing.get('id')})"
    )


def replace_existing_reference_warning(
    warnings: list[str] | None, existing: Mapping[str, Any] | None
) -> list[str] | None:
    """Retire l'ancien avertissement de référence, ajoute le nouveau si besoin."""
    kept = [
        w for w in warnings or [] if not str(w).startswith(EXISTING_REFERENCE_PREFIX)
    ]
    if existing is not None:
        kept.append(existing_reference_warning(existing))
    return kept or None
