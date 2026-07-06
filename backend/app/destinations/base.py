"""Destination port: where approved enrichment results are written.

The engine is destination-agnostic — it stages results on `enrichment_item`
and hands an approved item to a `Destination.apply`. `xano_tillin` is the first
adapter; `shopify_direct`, `woocommerce`, … can be added without touching the
engine.
"""

from typing import Protocol

from app.models import EnrichmentItem


class Destination(Protocol):
    """Writes an approved item's staged fields to a concrete catalog."""

    def apply(self, item: EnrichmentItem) -> None:
        """Push the item's staged enrichment; raise on failure."""
        ...
