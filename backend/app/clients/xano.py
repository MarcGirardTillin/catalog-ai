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
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel

from app.api.exceptions import AppException
from app.api.schemas import Brand, Product, ProductImage, ProductVariant

PRODUCTS_PATH = "/products_with_pagination"
PRODUCT_PATH = "/product"
BRANDS_PATH = "/brand"
CLASSIFICATION_PATH = "/get_all_informations"
LOGIN_PATH = "/auth/login"
PRODUCT_IMPORT_PATH = "/product_import"


def _enrich_path(product_id: int) -> str:
    return f"{PRODUCT_PATH}/{product_id}/enrich"


def _bulk_images_path(product_id: int) -> str:
    return f"/product_image/{product_id}/bulk"


def _brand_website_urls_path(brand_id: int) -> str:
    return f"{BRANDS_PATH}/{brand_id}/website_urls"


def normalize_website_urls(urls: list[str]) -> list[str]:
    """Scheme-normalize a list of brand website URLs, dropping empties."""
    return [u for u in (_normalize_url(str(v)) for v in urls) if u]


# Classification groups exposed for product-search filters, and how each maps
# onto the `products_with_pagination` filter param.
CLASSIFICATION_GROUPS = ("brands", "categories", "seasons", "suppliers", "tags")

logger = logging.getLogger(__name__)


def verify_login(
    base_url: str,
    email: str,
    password: str,
    *,
    data_source: str = "",
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any] | None:
    """Validate a user's Xano credentials; return their profile or None.

    Used to let Tillin/Xano users sign in to CatalogAI with their Xano
    identifiers. Returns `{email, full_name}` on success (best-effort name from
    `/auth/me`), or None when the credentials are rejected/unreachable.
    """
    headers = {"Accept": "application/json"}
    if data_source:
        headers["X-Data-Source"] = data_source
    try:
        with httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        ) as client:
            login = client.post(LOGIN_PATH, json={"email": email, "password": password})
            if login.status_code != 200:
                return None
            token = _first(login.json(), "authToken", "token")
            if not token:
                return None
            profile: dict[str, Any] = {"email": email, "full_name": None}
            me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            if me.status_code == 200 and isinstance(me.json(), Mapping):
                data = me.json()
                profile["full_name"] = _first(data, "name", "full_name")
                profile["email"] = _first(data, "email") or email
            return profile
    except httpx.HTTPError:
        logger.warning("Xano credential check failed to reach the API")
        return None


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


def _normalize_url(url: str) -> str:
    """Ensure a URL carries a scheme (Tillin data has bare/protocol-relative)."""
    url = url.strip().rstrip("/")
    if not url:
        return ""
    if url.startswith("//"):  # protocol-relative (e.g. `//cdn.host/...`)
        return f"https:{url}"
    if "://" not in url:  # bare host (e.g. `salomon.com`)
        return f"https://{url}"
    return url


def _collect_images(raw: Mapping[str, Any]) -> list[ProductImage]:
    """Gather a product's images: product-level first, then per-variant.

    Tillin exposes images both on the product (`product_images`) and on each
    variant (`product_image`); some products have only one or the other. URLs
    are scheme-normalized and de-duplicated, keeping product-level order.
    """
    images: list[ProductImage] = []
    seen: set[str] = set()

    def add(entry: Any) -> None:
        if not isinstance(entry, Mapping):
            return
        src = _normalize_url(str(_first(entry, "src", "url") or ""))
        if not src or src in seen:
            return
        seen.add(src)
        images.append(ProductImage(url=src, position=_first(entry, "position")))

    for entry in _as_list(raw.get("product_images")):
        add(entry)
    for variant in _as_list(raw.get("product_variants")):
        if isinstance(variant, Mapping):
            add(variant.get("product_image"))
    return images


def _to_urls(value: Any) -> list[str]:
    """Normalize a brand website field to a list of scheme-qualified URLs.

    Accepts whatever the Tillin brand table holds: a native list of strings
    (`website_urls`), a single text field, or a comma/space-separated string.
    Bare hosts (`salomon.com`) are given an `https://` scheme.
    """
    if not value:
        return []
    raw = value if isinstance(value, list) else str(value).replace(",", " ").split()
    return [u for u in (_normalize_url(str(v)) for v in raw) if u]


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


def _map_category(
    raw: Mapping[str, Any], categories: Mapping[int, str] | None
) -> str | None:
    """Resolve the category title from either raw Tillin product shape.

    The list shape (`/products_with_pagination`) nests the full category
    (`{"category": {"id": …, "title": …}}`); the detail shape (`/product/{id}`)
    only carries a flat `category_id`, resolved via the classification map.
    """
    category = raw.get("category")
    if isinstance(category, Mapping):
        name = _first(category, "title", "name")
        if name is not None:
            return str(name)
    category_id = raw.get("category_id")
    if categories and category_id is not None:
        try:
            return categories.get(int(category_id))
        except (TypeError, ValueError):
            return None
    return None


def _map_product(
    raw: Mapping[str, Any],
    brands: Mapping[int, Mapping[str, Any]] | None = None,
    categories: Mapping[int, str] | None = None,
) -> Product:
    """Map one raw Tillin product (list or detail shape) onto :class:`Product`."""
    variants_raw = [
        v for v in _as_list(raw.get("product_variants")) if isinstance(v, Mapping)
    ]
    return Product(
        id=_first(raw, "id", "product_id"),
        title=_first(raw, "title", "title_label"),
        reference_code=_first(raw, "product_reference_code"),
        brand=_map_brand(_first(raw, "brand_id"), brands or {}),
        category=_map_category(raw, categories),
        description=_first(raw, "description", "body_html"),
        meta_description=_first(raw, "meta_description"),
        variants=[_map_variant(v) for v in variants_raw],
        images=_collect_images(raw),
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
        self._categories: dict[int, str] | None = None

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

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        """POST with bearer auth; re-login once on 401 (expired token)."""
        if self._token is None:
            self._login()
        response = self._do_post(path, body)
        if response.status_code == 401:
            self._login()
            response = self._do_post(path, body)
        if response.status_code >= 400:
            raise XanoError(
                "Xano returned an error response",
                detail={"upstream_status": response.status_code},
            )
        try:
            return response.json()
        except ValueError:
            return None

    def _do_post(self, path: str, body: Mapping[str, Any]) -> httpx.Response:
        try:
            return self._client.post(
                path,
                json=dict(body),
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.TimeoutException as exc:
            raise XanoError(
                "Xano request timed out", code="xano_timeout", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            raise XanoError("Xano is unreachable", code="xano_unavailable") from exc

    def _post_multipart(
        self,
        path: str,
        *,
        files: Mapping[str, tuple[str, bytes, str]],
        data: Mapping[str, str],
    ) -> Any:
        """POST multipart/form-data with bearer auth; re-login once on 401."""
        if self._token is None:
            self._login()
        response = self._do_post_multipart(path, files=files, data=data)
        if response.status_code == 401:
            self._login()
            response = self._do_post_multipart(path, files=files, data=data)
        if response.status_code >= 400:
            raise XanoError(
                "Xano returned an error response",
                detail={"upstream_status": response.status_code},
            )
        try:
            return response.json()
        except ValueError:
            return None

    def _do_post_multipart(
        self,
        path: str,
        *,
        files: Mapping[str, tuple[str, bytes, str]],
        data: Mapping[str, str],
    ) -> httpx.Response:
        try:
            return self._client.post(
                path,
                files=dict(files),
                data=dict(data),
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

    def _category_map(self) -> dict[int, str]:
        """Lazily load and cache the `{category_id: title}` map.

        Sourced from the classification endpoint (same payload as the search
        filters). Best-effort like `_brand_map`: on failure the map is cached
        empty and detail products simply keep `category=None` (never raises).
        """
        if self._categories is not None:
            return self._categories
        categories: dict[int, str] = {}
        try:
            for option in self.get_classification().get("categories", []):
                categories[int(option["id"])] = str(option["title"])
        except XanoError:
            logger.warning("could not load Xano categories; category names omitted")
        self._categories = categories
        return categories

    # -- reads --------------------------------------------------------------

    def list_brands(self) -> list[Brand]:
        """Fetch every brand (`GET /brand`) as canonical Brands, sorted by name.

        Unlike `_brand_map` (best-effort cache used to decorate products), this
        read backs a dedicated screen and therefore surfaces upstream failures
        as :class:`XanoError`. Brands without a name sort last.
        """
        payload = self._request(BRANDS_PATH, {})
        brands: list[Brand] = []
        for raw in _as_list(payload):
            if not isinstance(raw, Mapping) or raw.get("id") is None:
                continue
            brand = _map_brand(raw["id"], {int(raw["id"]): raw})
            if brand is not None:
                brands.append(brand)
        brands.sort(key=lambda b: (b.name is None, (b.name or "").lower()))
        return brands

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
        return _map_product(payload, self._brand_map(), self._category_map())

    def get_classification(self) -> dict[str, list[dict[str, Any]]]:
        """Classification lists for search filters (brands, categories, …).

        Each group is normalized to `{id, title, parent_id?}` options, sorted
        by title. Sources the company's `/get_all_informations` payload.
        """
        payload = self._request(CLASSIFICATION_PATH, {})
        company = (
            payload.get("company_all_informations")
            if isinstance(payload, Mapping)
            else None
        )
        result: dict[str, list[dict[str, Any]]] = {g: [] for g in CLASSIFICATION_GROUPS}
        if not isinstance(company, Mapping):
            return result
        for group in CLASSIFICATION_GROUPS:
            options: list[dict[str, Any]] = []
            for raw in _as_list(company.get(group)):
                if not isinstance(raw, Mapping) or raw.get("id") is None:
                    continue
                title = _first(raw, "title", "name")
                if not title:  # skip unnamed rows (some seasons have title=None)
                    continue
                option: dict[str, Any] = {"id": int(raw["id"]), "title": str(title)}
                if "parent_id" in raw:
                    option["parent_id"] = raw.get("parent_id")
                options.append(option)
            options.sort(key=lambda o: o["title"].lower())
            result[group] = options
        return result

    def list_locations(self) -> list[dict[str, Any]]:
        """Tillin-owned locations `{id, title}`, sorted by title.

        Sourced from `/get_all_informations` (`company_all_informations.
        locations`). Locations whose `origin` looks third-party (marketplace
        feeds synced from elsewhere) are excluded: they must never receive a
        product import.
        """
        payload = self._request(CLASSIFICATION_PATH, {})
        company = (
            payload.get("company_all_informations")
            if isinstance(payload, Mapping)
            else None
        )
        locations: list[dict[str, Any]] = []
        if not isinstance(company, Mapping):
            return locations
        for raw in _as_list(company.get("locations")):
            if not isinstance(raw, Mapping) or raw.get("id") is None:
                continue
            origin = str(raw.get("origin") or "").lower().replace("-", "_")
            if "third" in origin:
                continue
            title = _first(raw, "title", "name")
            locations.append({"id": int(raw["id"]), "title": str(title or "")})
        locations.sort(key=lambda location: str(location["title"]).lower())
        return locations

    # -- writes (enrichment apply) -----------------------------------------

    def enrich_product(
        self,
        product_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        meta_description: str | None = None,
    ) -> None:
        """Write staged copy back to Tillin (`/product/{id}/enrich`).

        Only the provided fields are sent; None values are omitted so the
        endpoint leaves them untouched.
        """
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if meta_description is not None:
            body["meta_description"] = meta_description
        if not body:
            return
        self._post(_enrich_path(product_id), body)

    def add_product_images(self, product_id: int, image_urls: list[str]) -> None:
        """Append images to a product from URLs (`/product_image/{id}/bulk`).

        NOTE: the endpoint appends — it does not replace existing images.
        """
        urls = [u for u in image_urls if u]
        if not urls:
            return
        self._post(_bulk_images_path(product_id), {"image_urls": urls})

    def set_brand_website_urls(self, brand_id: int, urls: list[str]) -> None:
        """Replace a brand's reference websites (`/brand/{id}/website_urls`).

        URLs are scheme-normalized and empties dropped before sending. The
        response body shape is unknown, so it is ignored (best-effort). The
        brand cache is invalidated so subsequent product reads see the update.
        """
        normalized = normalize_website_urls(urls)
        # The Xano endpoint expects brand_id in the body too (not only the path).
        self._post(
            _brand_website_urls_path(brand_id),
            {"brand_id": brand_id, "website_urls": normalized},
        )
        self._brands = None

    def product_import(
        self, *, file_name: str, csv_bytes: bytes, location_id: int
    ) -> Any:
        """Upload a Tillin import CSV to a location (`POST /product_import`).

        Multipart write: the CSV travels as the `file_import` part, the target
        location as a form field. Returns the raw upstream payload (shape
        unknown — callers only rely on success/failure).
        """
        return self._post_multipart(
            PRODUCT_IMPORT_PATH,
            files={"file_import": (file_name, csv_bytes, "text/csv")},
            data={"location_id": str(location_id)},
        )
