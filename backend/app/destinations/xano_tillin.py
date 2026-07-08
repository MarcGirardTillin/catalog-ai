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


def _filter_image_urls(urls: list[str], selected: Any) -> list[str]:
    """Keep only the reviewer-selected image URLs, in staged order.

    `selected` is `apply_fields_json["image_urls"]`: absent (or not a list)
    means "apply all"; an empty list means "apply none"; URLs not present in
    the staged set are ignored.
    """
    if not isinstance(selected, list):
        return urls
    wanted = {str(u) for u in selected}
    return [u for u in urls if u in wanted]


def _selected_weights(
    staged_weights_json: Any, selected_ids: Any
) -> list[dict[str, Any]]:
    """Filter staged weight proposals by reviewer-selected variant ids.

    `selected_ids` is `apply_fields_json["weight_variant_ids"]`: absent (or
    not a list) means "apply all"; an empty list means "apply none"; unknown
    variant ids are ignored.
    """
    entries: list[dict[str, Any]] = [
        e for e in staged_weights_json or [] if isinstance(e, dict)
    ]
    if not isinstance(selected_ids, list):
        return entries
    wanted: set[int] = set()
    for value in selected_ids:
        try:
            wanted.add(int(value))
        except (TypeError, ValueError):
            continue
    selected: list[dict[str, Any]] = []
    for entry in entries:
        try:
            variant_id = int(entry["variant_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if variant_id in wanted:
            selected.append(entry)
    return selected


class XanoTillinDestination:
    """Applies staged enrichment to the Tillin catalog via Xano."""

    def __init__(self, client: XanoClient) -> None:
        self._client = client

    def apply(self, item: EnrichmentItem) -> None:
        # Reviewer's per-field keep/drop: a missing key means "apply it".
        include: dict[str, Any] = item.apply_fields_json or {}

        if include.get("images", True):
            urls = _filter_image_urls(
                _image_urls(item.staged_images_json), include.get("image_urls")
            )
            if urls:
                self._client.add_product_images(item.tillin_product_id, urls)
        copy = {
            "title": item.staged_title if include.get("title", True) else None,
            "description": item.staged_description
            if include.get("description", True)
            else None,
            "meta_description": item.staged_meta if include.get("meta", True) else None,
        }
        if any(value is not None for value in copy.values()):
            self._client.enrich_product(item.tillin_product_id, **copy)

        # Weights: the reviewer selection (`weights` bool + `weight_variant_ids`)
        # is honored here, but nothing is sent yet — weights writeback needs the
        # Xano set_variant_weights endpoint (plan infra).
        if include.get("weights", True):
            _selected_weights(
                item.staged_weights_json, include.get("weight_variant_ids")
            )
