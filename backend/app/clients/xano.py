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

from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from app.api.exceptions import AppException
from app.api.schemas import Brand, Product, ProductImage, ProductVariant

PRODUCTS_PATH = "/products_with_pagination"
PRODUCT_PATH = "/product"
LOGIN_PATH = "/auth/login"


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


def _map_product(raw: Mapping[str, Any]) -> Product:
    """Map one raw Tillin product (list or detail shape) onto :class:`Product`.

    Brand is carried as an id only — the Tillin product payload has no nested
    brand and no website URL; the brand's source site(s) live in CatalogAI.
    """
    variants_raw = [
        v for v in _as_list(raw.get("product_variants")) if isinstance(v, Mapping)
    ]
    brand_id = _first(raw, "brand_id")
    brand = Brand(id=brand_id) if brand_id else None
    category = raw.get("category")
    category_name = (
        _first(category, "title", "name") if isinstance(category, Mapping) else None
    )
    return Product(
        id=_first(raw, "id", "product_id"),
        title=_first(raw, "title", "title_label"),
        reference_code=_first(raw, "product_reference_code"),
        brand=brand,
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
        raw_items = payload.get("items")
        items = [
            _map_product(item)
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
        return _map_product(payload)
