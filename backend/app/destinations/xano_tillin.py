"""Tillin (Xano) destination adapter — writes staged enrichment back.

Maps an approved `enrichment_item` onto Tillin's write endpoints:
- copy (title, description, meta) → `POST /product/{id}/enrich`
- images (URLs)                   → `POST /product_image/{id}/bulk`

Images are pushed first so a copy failure doesn't leave images orphaned mid
apply; both are idempotent per call but the bulk endpoint *appends*, so callers
must not re-apply an already-applied item (the `applied` status guards this).
"""

from typing import Any

from app.clients.xano import XanoClient
from app.models import EnrichmentItem


def _image_urls(staged_images_json: Any) -> list[str]:
    urls: list[str] = []
    for entry in staged_images_json or []:
        if isinstance(entry, dict) and entry.get("url"):
            urls.append(str(entry["url"]))
        elif isinstance(entry, str) and entry:
            urls.append(entry)
    return urls


class XanoTillinDestination:
    """Applies staged enrichment to the Tillin catalog via Xano."""

    def __init__(self, client: XanoClient) -> None:
        self._client = client

    def apply(self, item: EnrichmentItem) -> None:
        # Reviewer's per-field keep/drop: a missing key means "apply it".
        include: dict[str, Any] = item.apply_fields_json or {}

        urls = _image_urls(item.staged_images_json)
        if urls and include.get("images", True):
            self._client.add_product_images(item.tillin_product_id, urls)
        copy = {
            "title": item.staged_title if include.get("title", True) else None,
            "description": item.staged_description
            if include.get("description", True)
            else None,
            "meta_description": item.staged_meta
            if include.get("meta", True)
            else None,
        }
        if any(value is not None for value in copy.values()):
            self._client.enrich_product(item.tillin_product_id, **copy)
