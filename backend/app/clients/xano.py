"""Tillin REST API (Xano) client — read path.

Wraps the Tillin Xano workspace behind a typed interface and maps its raw
payloads onto the canonical :mod:`app.api.schemas.product` models. This is the
first destination adapter's read side; writes (enrich/apply) come later.

Auth is email/password login → a bearer ``authToken`` (JWT); the token is
cached and transparently refreshed once on a 401. An optional
``X-Data-Source`` header selects the Xano datasource (``test`` for the seeded
test data). Raw Tillin field names are isolated in ``_map_*`` so the live
contract lives in one place.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from app.api.exceptions import AppException
from app.api.schemas import Brand, Product, ProductImage, ProductVariant

PRODUCTS_PATH = "/products_with_pagination"
PRODUCT_PATH = "/product"
BRANDS_PATH = "/brand"
LOGIN_PATH = "/auth/login"

logger = logging.getLogger(__name__)


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


def _map_variant(raw: Mapping[str, Any]) -> ProductVariant:
    return ProductVariant(
        id=_first(raw, "id", "variant_id"),
        sku=_first(raw, "sku"),
        barcode=_first(raw, "barcode"),
        weight=_first(raw, "weight"),
        weight_unit=_first(raw, "weight_unit"),
    )


def _variant_images(variants: Sequence[Mapping[str, Any]]) -> list[ProductImage]:
    """Tillin images live on variants (`product_image.src`), not the product."""
    images: list[ProductImage] = []
    seen: set[str] = set()
    for variant in variants:
        raw = variant.get("product_image")
        if not isinstance(raw, Mapping):
            continue
        src = _first(raw, "src", "url")
        if not src or str(src) in seen:
            continue
        seen.add(str(src))
        images.append(ProductImage(url=str(src), position=_first(raw, "position")))
    return images


def _to_urls(value: Any) -> list[str]:
    """Normalize a brand website field to a list of URLs.

    Accepts whatever the Tillin brand table holds: a single text field
    (`brand_website`), a comma/space-separated string, or a native list of
    strings (`website_urls`). Unknown shapes yield an empty list.
    """
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v and str(v).strip()]
    parts = str(value).replace(",", " ").split()
    return [p for p in parts if p]


def _map_brand(brand_id: Any, brands: Mapping[int, Mapping[str, Any]]) -> Brand | None:
    """Resolve a product's `brand_id` to a canonical Brand (name + site URLs).

    The Tillin product payload carries only `brand_id`; the brand's title and
    website(s) come from the separately-fetched `/brand` map. Both a single
    `brand_website` text field and a `website_urls` list are supported.
    """
    if not brand_id:
        return None
    info = brands.get(int(brand_id), {})
    return Brand(
        id=int(brand_id),
        name=_first(info, "title", "name") if info else None,
        website_urls=_to_urls(_first(info, "website_urls", "brand_website"))
        if info
        else [],
    )


def _map_product(
    raw: Mapping[str, Any], brands: Mapping[int, Mapping[str, Any]] | None = None
) -> Product:
    """Map one raw Tillin product (list or detail shape) onto :class:`Product`."""
    variants_raw = [
        v for v in _as_list(raw.get("product_variants")) if isinstance(v, Mapping)
    ]
    category = raw.get("category")
    category_name = (
        _first(category, "title", "name") if isinstance(category, Mapping) else None
    )
    return Product(
        id=_first(raw, "id", "product_id"),
        title=_first(raw, "title", "title_label"),
        reference_code=_first(raw, "product_reference_code"),
        brand=_map_brand(_first(raw, "brand_id"), brands or {}),
        category=category_name,
        variants=[_map_variant(v) for v in variants_raw],
        images=_variant_images(variants_raw),
    )


class XanoClient:
    """Thin REST wrapper around the Tillin Xano workspace (login-authed)."""

    def __init__(
        self,
        base_url: str,
        *,
        email: str,
        password: str,
        data_source: str = "",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._email = email
        self._password = password
        headers = {"Accept": "application/json"}
        if data_source:
            headers["X-Data-Source"] = data_source
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self._token: str | None = None
        self._brands: dict[int, Mapping[str, Any]] | None = None

    def __enter__(self) -> "XanoClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- auth ---------------------------------------------------------------

    def _login(self) -> str:
        try:
            response = self._client.post(
                LOGIN_PATH,
                json={"email": self._email, "password": self._password},
            )
        except httpx.HTTPError as exc:
            raise XanoError(
                "Xano login is unreachable", code="xano_unavailable"
            ) from exc
        if response.status_code >= 400:
            raise XanoError(
                "Xano login failed",
                code="xano_login_failed",
                status_code=502,
                detail={"upstream_status": response.status_code},
            )
        token = _first(response.json(), "authToken", "token")
        if not token:
            raise XanoError("Xano login returned no token")
        self._token = str(token)
        return self._token

    def _request(self, path: str, params: Mapping[str, Any]) -> Any:
        """GET with bearer auth; re-login once on 401 (expired token)."""
        if self._token is None:
            self._login()
        response = self._do_get(path, params)
        if response.status_code == 401:
            self._login()
            response = self._do_get(path, params)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise XanoError(
                "Xano returned an error response",
                detail={"upstream_status": response.status_code},
            )
        try:
            return response.json()
        except ValueError as exc:
            raise XanoError("Xano returned a non-JSON response") from exc

    def _do_get(self, path: str, params: Mapping[str, Any]) -> httpx.Response:
        try:
            return self._client.get(
                path,
                params=dict(params),
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.TimeoutException as exc:
            raise XanoError(
                "Xano request timed out", code="xano_timeout", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            raise XanoError("Xano is unreachable", code="xano_unavailable") from exc

    def _brand_map(self) -> dict[int, Mapping[str, Any]]:
        """Lazily load and cache the `{brand_id: brand}` map from `/brand`.

        Brand enrichment is best-effort: if the endpoint is unavailable the map
        is cached empty and products keep their `brand_id` only (never raises).
        """
        if self._brands is not None:
            return self._brands
        brands: dict[int, Mapping[str, Any]] = {}
        try:
            payload = self._request(BRANDS_PATH, {})
            for raw in _as_list(payload):
                if isinstance(raw, Mapping) and raw.get("id") is not None:
                    brands[int(raw["id"])] = raw
        except XanoError:
            logger.warning("could not load Xano brands; brand names/URLs omitted")
        self._brands = brands
        return brands

    # -- reads --------------------------------------------------------------

    def search_products(
        self,
        *,
        text: str | None = None,
        brand: int | None = None,
        category: int | None = None,
        supplier: int | None = None,
        season: int | None = None,
        tag: int | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> ProductPage:
        """Search the catalog (free text + filters), paginated."""
        params: dict[str, Any] = {
            "external[page]": page,
            "external[per_page]": per_page,
        }
        if text:
            params["search_query_text"] = text
        if brand:
            params["search_query_brand"] = brand
        if category:
            params["search_query_category"] = category
        if supplier:
            params["search_query_supplier"] = supplier
        if season:
            params["search_query_season"] = season
        if tag:
            params["search_query_tag"] = tag
        if status:
            params["search_query_status"] = status

        payload = self._request(PRODUCTS_PATH, params)
        if not isinstance(payload, Mapping):
            return ProductPage(items=[], total=0, page=page, per_page=per_page)
        brands = self._brand_map()
        raw_items = payload.get("items")
        items = [
            _map_product(item, brands)
            for item in (raw_items if isinstance(raw_items, list) else [])
            if isinstance(item, Mapping)
        ]
        total = _first(payload, "itemsTotal", "total") or len(items)
        return ProductPage(items=items, total=int(total), page=page, per_page=per_page)

    def get_product(self, product_id: int) -> Product | None:
        """Fetch one product's full detail by id, or None when absent."""
        payload = self._request(f"{PRODUCT_PATH}/{product_id}", {})
        if not isinstance(payload, Mapping):
            return None
        return _map_product(payload, self._brand_map())
