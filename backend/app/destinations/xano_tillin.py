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
from app.clients.base import ExternalServiceError
from app.clients.xano import FilePart, XanoClient
from app.imaging import staging
from app.imaging.naming import render_image_filename
from app.imaging.service import download_source_image
from app.imaging.uploads import prepare_upload
from app.models import EnrichmentItem, ImageAsset

logger = logging.getLogger(__name__)

# Staged weights are normalized to kg by the pipeline; map to Tillin's codes
# (1=kg, 2=g, 3=lb, 4=oz) defensively in case that ever changes.
_WEIGHT_UNIT_CODES = {"kg": "1", "g": "2", "lb": "3", "oz": "4"}


def _depipe(value: str | None) -> str | None:
    """« | » → « / » dans les valeurs écrites vers Tillin (décision Marc
    2026-07-18 — le pipe est un séparateur pour les gabarits de titre)."""
    if not value or "|" not in value:
        return value
    return " / ".join(part.strip() for part in value.split("|") if part.strip())


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

    def apply(self, item: EnrichmentItem) -> list[str]:
        # Reviewer's per-field keep/drop: a missing key means "apply it".
        include: dict[str, Any] = item.apply_fields_json or {}

        warnings: list[str] = []
        if include.get("images", True):
            entries = _filter_image_entries(
                _image_entries(item.staged_images_json), include.get("image_urls")
            )
            warnings = self._push_images(item, entries)
        copy = {
            "title": _depipe(item.staged_title) if include.get("title", True) else None,
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
            else:
                # Aucune proposition de poids (page sans variantes, extraction
                # web…) : repli sur le poids par défaut de la catégorie
                # (table catégorie Xano, décision Marc 2026-07-25) — seulement
                # si le produit n'a pas déjà un poids.
                self._apply_category_default_weight(item)

        return warnings

    def _apply_category_default_weight(self, item: EnrichmentItem) -> None:
        """Best-effort : poids par défaut de la catégorie du produit."""
        try:
            product = self._client.get_product(item.tillin_product_id)
        except Exception:  # pragma: no cover - réseau, best-effort
            return
        if product is None or not (product.category or "").strip():
            return
        if any(v.weight for v in product.variants):
            return  # un poids existe déjà : ne jamais l'écraser
        weights = self._client.category_default_weights()
        default = weights.get(str(product.category).strip().lower())
        if default:
            self._client.set_product_weight([item.tillin_product_id], default, "1")

    def _push_images(
        self, item: EnrichmentItem, entries: list[dict[str, Any]]
    ) -> list[str]:
        """Push the selected image entries as BYTES, and verify the outcome.

        Raw source URLs are downloaded by CatalogAI itself (browser identity)
        then normalized by ``prepare_upload`` — pushing URLs to Xano let ITS
        server-side fetch fail silently on anti-bot CDNs (vécu Farfetch :
        review OK, Tillin vide). Normalized entries keep their staged bytes.
        Everything goes through ONE multipart bulk upload, whose response is
        compared to what was sent ; a source we cannot download falls back to
        the URL push (Xano may still succeed from its own IPs), itself
        verified. Partial outcomes never fail the apply : they come back as
        human-readable warnings surfaced on the item.

        All staged bytes are loaded BEFORE any write so a purged/missing
        staging fails the apply cleanly instead of uploading a partial set.
        """
        if not entries:
            return []
        db = object_session(item)
        if db is None and any(e.get("asset_id") for e in entries):
            # pragma: no cover - defensive
            raise AppException(
                status_code=500,
                code="staging_unavailable",
                message="Cannot load normalized images: item has no session",
            )
        warnings: list[str] = []
        stems = (
            self._template_stems(db, item, entries)
            if db is not None
            else [None] * len(entries)
        )

        uploads: list[tuple[ImageAsset | None, FilePart]] = []
        url_fallback: list[str] = []
        for index, (entry, stem) in enumerate(zip(entries, stems, strict=True)):
            if entry.get("asset_id"):
                assert db is not None  # guarded above
                uploads.append(self._load_upload(db, entry, stem=stem))
                continue
            url = str(entry["url"])
            try:
                data = download_source_image(url)
                filename = stem or url.split("?")[0].split("#")[0]
                uploads.append((None, prepare_upload(filename, data, index=index)))
            except (ExternalServiceError, AppException) as exc:
                logger.warning(
                    "item %s: could not fetch/prepare %s locally (%s) — "
                    "falling back to the Xano URL import",
                    item.id,
                    url,
                    exc,
                )
                url_fallback.append(url)

        if uploads:
            created = self._client.upload_product_images(
                item.tillin_product_id, [part for _, part in uploads]
            )
            if len(created) == len(uploads):
                for (asset, _), image in zip(uploads, created, strict=True):
                    if asset is not None:
                        if image.id is not None:
                            asset.tillin_image_ids_json = [image.id]
                        staging.purge_asset(asset.id)
            else:
                # Tillin en a refusé une partie sans dire lesquelles :
                # l'appariement positionnel n'est plus fiable — on n'assigne
                # rien, on ne purge rien, on remonte l'écart.
                missing = len(uploads) - len(created)
                warnings.append(
                    f"{missing} image(s) sur {len(uploads)} refusée(s) par "
                    "Tillin à l'upload"
                )
        if url_fallback:
            created_from_urls = self._client.add_product_images(
                item.tillin_product_id, url_fallback
            )
            missing = len(url_fallback) - len(created_from_urls)
            if missing > 0:
                warnings.append(
                    f"{missing} image(s) sur {len(url_fallback)} n'ont pas pu "
                    "être importées par Tillin depuis leur URL d'origine "
                    "(site source protégé)"
                )
        return warnings

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
