"""Tillin (Xano) destination adapter — writes staged enrichment back.

Maps an approved `enrichment_item` onto Tillin's write endpoints:
- copy (title, description, meta) → `POST /product/{id}/enrich`
- images (URLs)                   → `POST /product_image/{id}/bulk`
- images (normalized files)       → `POST /product_image/{id}/bulk` (multipart)
- weight                          → `POST /product/weight`

Staged image entries come in two shapes: raw source URLs (`{"url", "position"}`,
pushed by URL) and Photoroom-normalized entries (`{"url", "position",
"asset_id", "source_url"}`, whose bytes are read from the imaging staging and
uploaded). Images are pushed first so a copy failure doesn't leave images
orphaned mid apply; both are idempotent per call but the bulk endpoint
*appends*, so callers must not re-apply an already-applied item (the `applied`
status guards this).
"""

import logging
from typing import Any

from sqlalchemy.orm import Session, object_session

from app.api.exceptions import AppException
from app.api.services.imaging import MEDIA_TYPES, account_settings
from app.clients.xano import FilePart, XanoClient
from app.imaging import staging
from app.imaging.naming import render_image_filename
from app.models import EnrichmentItem, ImageAsset

logger = logging.getLogger(__name__)

# Staged weights are normalized to kg by the pipeline; map to Tillin's codes
# (1=kg, 2=g, 3=lb, 4=oz) defensively in case that ever changes.
_WEIGHT_UNIT_CODES = {"kg": "1", "g": "2", "lb": "3", "oz": "4"}


def _image_entries(staged_images_json: Any) -> list[dict[str, Any]]:
    """Normalize staged entries to dicts with a `url` key (legacy strings too)."""
    entries: list[dict[str, Any]] = []
    for entry in staged_images_json or []:
        if isinstance(entry, dict) and entry.get("url"):
            entries.append(entry)
        elif isinstance(entry, str) and entry:
            entries.append({"url": entry})
    return entries


def _filter_image_entries(
    entries: list[dict[str, Any]], selected: Any
) -> list[dict[str, Any]]:
    """Keep only the reviewer-selected image entries, in staged order.

    `selected` is `apply_fields_json["image_urls"]`, matched against each
    entry's `url`: absent (or not a list) means "apply all"; an empty list
    means "apply none"; URLs not present in the staged set are ignored.
    """
    if not isinstance(selected, list):
        return entries
    wanted = {str(u) for u in selected}
    return [e for e in entries if str(e["url"]) in wanted]


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
            entries = _filter_image_entries(
                _image_entries(item.staged_images_json), include.get("image_urls")
            )
            self._push_images(item, entries)
        copy = {
            "title": item.staged_title if include.get("title", True) else None,
            "description": item.staged_description
            if include.get("description", True)
            else None,
            "meta_description": item.staged_meta if include.get("meta", True) else None,
        }
        if any(value is not None for value in copy.values()):
            self._client.enrich_product(item.tillin_product_id, **copy)

        # Weights: `/product/weight` is product-level (one weight per product),
        # so we reduce the reviewer-selected variant proposals to a single value.
        # Per the boutique convention, all variants share one weight → take the
        # first selected proposal.
        if include.get("weights", True):
            selected = _selected_weights(
                item.staged_weights_json, include.get("weight_variant_ids")
            )
            if selected:
                first = selected[0]
                weight = first.get("weight")
                unit = _WEIGHT_UNIT_CODES.get(
                    str(first.get("weight_unit", "kg")).lower(), "1"
                )
                if weight is not None:
                    self._client.set_product_weight(
                        [item.tillin_product_id], float(weight), unit
                    )

    def _push_images(self, item: EnrichmentItem, entries: list[dict[str, Any]]) -> None:
        """Push the selected image entries: raw URLs by URL, normalized ones
        as staged bytes (multipart bulk upload).

        All staged bytes are loaded BEFORE any write so a purged/missing
        staging fails the apply cleanly instead of uploading a partial set.
        """
        raw_urls = [str(e["url"]) for e in entries if not e.get("asset_id")]
        asset_entries = [e for e in entries if e.get("asset_id")]

        uploads: list[tuple[ImageAsset, FilePart]] = []
        if asset_entries:
            db = object_session(item)
            if db is None:  # pragma: no cover - defensive
                raise AppException(
                    status_code=500,
                    code="staging_unavailable",
                    message="Cannot load normalized images: item has no session",
                )
            stems = self._template_stems(db, item, asset_entries)
            for entry, stem in zip(asset_entries, stems, strict=True):
                uploads.append(self._load_upload(db, entry, stem=stem))

        if raw_urls:
            self._client.add_product_images(item.tillin_product_id, raw_urls)
        if uploads:
            created = self._client.upload_product_images(
                item.tillin_product_id, [part for _, part in uploads]
            )
            created_ids = [image.id for image in created]
            for index, (asset, _) in enumerate(uploads):
                if index < len(created_ids) and created_ids[index] is not None:
                    asset.tillin_image_ids_json = [created_ids[index]]
                staging.purge_asset(asset.id)

    def _template_stems(
        self, db: Session, item: EnrichmentItem, entries: list[dict[str, Any]]
    ) -> list[str | None]:
        """File stems rendered by the account's image title template.

        None entries fall back to the technical default. Best effort: a
        missing product or a template error never fails the apply.
        """
        template = (
            account_settings(db, item.account_id).image_title_template or ""
        ).strip()
        if not template:
            return [None] * len(entries)
        try:
            product = self._client.get_product(item.tillin_product_id)
        except Exception:  # pragma: no cover - defensive (network)
            product = None
        if product is None:
            return [None] * len(entries)
        stems: list[str | None] = []
        for index, entry in enumerate(entries):
            position = int(entry.get("position") or index + 1)
            try:
                stems.append(render_image_filename(product, position, template) or None)
            except ValueError:  # unknown token in a hand-edited template
                stems.append(None)
        return stems

    def _load_upload(
        self, db: Session, entry: dict[str, Any], *, stem: str | None = None
    ) -> tuple[ImageAsset, FilePart]:
        """Resolve one normalized entry to (asset, multipart file part)."""
        asset_id = int(entry["asset_id"])
        asset = db.get(ImageAsset, asset_id)
        staged = list(asset.staged_paths_json or []) if asset is not None else []
        if asset is None or not staged:
            raise AppException(
                status_code=409,
                code="staging_missing",
                message=(
                    f"Normalized image (asset {asset_id}) has no staged file — "
                    "re-run the enrichment before applying"
                ),
            )
        relpath = str(staged[0])
        try:
            data = staging.load(relpath)
        except (FileNotFoundError, ValueError) as exc:
            raise AppException(
                status_code=409,
                code="staging_missing",
                message=(
                    f"Staged file for normalized image (asset {asset_id}) is "
                    "gone — re-run the enrichment before applying"
                ),
            ) from exc
        extension = relpath.rsplit(".", 1)[-1].lower()
        position = entry.get("position") or 0
        filename = f"{stem or f'normalize_{asset_id}_{position}'}.{extension}"
        content_type = MEDIA_TYPES.get(extension, "application/octet-stream")
        return asset, (filename, data, content_type)
