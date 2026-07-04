"""Tillin REST API (Xano) client — read path.

Wraps the Tillin Xano workspace behind a typed interface and maps its raw
payloads onto the canonical :mod:`app.api.schemas.product` models. This is the
first destination adapter's read side; writes (enrich/apply) come later.

The exact Tillin field names below are best-effort and isolated in
``_map_product`` / ``_map_variant`` — confirm them against the live
``products_with_pagination*`` endpoints and adjust the aliases in one place.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from app.api.exceptions import AppException
from app.api.schemas import Brand, Product, ProductImage, ProductVariant

# Default Tillin endpoint for paginated product reads. Override per deployment
# if the workspace exposes a different path.
PRODUCTS_PATH = "/products_with_pagination"


class XanoError(AppException):
    """Raised when a call to the Xano upstream fails."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "xano_error",
        status_code: int = 502,
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code, code=code, message=message, detail=detail
        )


class ProductPage(BaseModel):
    """A page of canonical products returned by the client."""

    items: list[Product]
    total: int
    page: int
    per_page: int


def _first(source: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present, non-null value among ``keys``."""
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _map_brand(raw: Any) -> Brand | None:
    if not isinstance(raw, Mapping):
        return None
    website = _first(raw, "website_urls", "website_url")
    return Brand(
        id=_first(raw, "id", "brand_id"),
        name=_first(raw, "name", "title"),
        website_urls=[str(url) for url in _as_list(website) if url],
    )


def _map_variant(raw: Mapping[str, Any]) -> ProductVariant:
    return ProductVariant(
        id=_first(raw, "id", "variant_id", "product_variant_id"),
        sku=_first(raw, "sku", "product_variant_sku"),
        barcode=_first(raw, "barcode", "product_variant_barcode", "ean", "upc"),
        weight=_first(raw, "weight", "product_variant_weight"),
        weight_unit=_first(raw, "weight_unit", "product_variant_weight_unit"),
    )


def _map_image(raw: Any) -> ProductImage | None:
    if isinstance(raw, str):
        return ProductImage(url=raw)
    if isinstance(raw, Mapping):
        url = _first(raw, "url", "src", "image_url")
        if url:
            return ProductImage(url=str(url), position=_first(raw, "position", "order"))
    return None


def _map_product(raw: Mapping[str, Any]) -> Product:
    """Map one raw Tillin product onto the canonical :class:`Product`."""
    variants = [
        _map_variant(v)
        for v in _as_list(_first(raw, "variants", "product_variants"))
        if isinstance(v, Mapping)
    ]
    images = [
        image
        for image in (
            _map_image(i) for i in _as_list(_first(raw, "images", "product_images"))
        )
        if image is not None
    ]
    return Product(
        id=_first(raw, "id", "product_id"),
        title=_first(raw, "title", "name", "product_name"),
        reference_code=_first(raw, "product_reference_code", "reference_code"),
        brand=_map_brand(_first(raw, "brand", "_brand")),
        season=_first(raw, "season"),
        category=_first(raw, "category"),
        department=_first(raw, "department"),
        variants=variants,
        images=images,
    )


def _extract_items(payload: Any) -> tuple[list[Any], int]:
    """Pull the item list and total out of a Xano pagination payload."""
    if isinstance(payload, list):
        return payload, len(payload)
    if isinstance(payload, Mapping):
        items = _first(payload, "items", "data", "results") or []
        if not isinstance(items, list):
            items = []
        total = _first(payload, "itemsTotal", "total", "count")
        return items, int(total) if total is not None else len(items)
    return [], 0


class XanoClient:
    """Thin REST wrapper around the Tillin Xano workspace.

    Use as a context manager or call :meth:`close` explicitly.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> "XanoClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: Mapping[str, Any]) -> Any:
        try:
            response = self._client.get(path, params=dict(params))
        except httpx.TimeoutException as exc:
            raise XanoError(
                "Xano request timed out", code="xano_timeout", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            raise XanoError(
                "Xano is unreachable", code="xano_unavailable", status_code=502
            ) from exc

        if response.status_code >= 400:
            raise XanoError(
                "Xano returned an error response",
                detail={"upstream_status": response.status_code},
            )
        try:
            return response.json()
        except ValueError as exc:
            raise XanoError("Xano returned a non-JSON response") from exc

    def list_products(
        self,
        *,
        tag: str | None = None,
        ids: Sequence[int] | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> ProductPage:
        """Read products by ``tag`` or by explicit ``ids`` (provide exactly one)."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if tag is not None:
            params["tag"] = tag
        if ids:
            params["ids"] = ",".join(str(i) for i in ids)

        payload = self._get(PRODUCTS_PATH, params)
        raw_items, total = _extract_items(payload)
        items = [_map_product(item) for item in raw_items if isinstance(item, Mapping)]
        return ProductPage(items=items, total=total, page=page, per_page=per_page)
