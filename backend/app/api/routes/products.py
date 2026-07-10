"""Product selection route — searches the Tillin catalog through Xano.

Backs the CatalogAI selection screen: free-text search + filters over the
Tillin catalog so the user can pick product ids, then build an enrichment job
from that selection. The Xano bearer token never reaches the browser — the
backend proxies the call behind the session cookie.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.api.deps import XanoDep, get_current_user
from app.api.exceptions import AppException
from app.api.schemas import PaginatedResponse, Product, ProductImagesUploadResult

# Guardrails for the upload route (a boutique adds a handful of shots at a time).
MAX_UPLOAD_FILES = 20
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB per file

router = APIRouter(
    prefix="/products",
    tags=["products"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=PaginatedResponse[Product])
def list_products(
    xano: XanoDep,
    search: Annotated[str | None, Query(description="Free-text search")] = None,
    brand: Annotated[int | None, Query(description="Filter by brand id")] = None,
    category: Annotated[int | None, Query(description="Filter by category id")] = None,
    supplier: Annotated[int | None, Query(description="Filter by supplier id")] = None,
    season: Annotated[int | None, Query(description="Filter by season id")] = None,
    tag: Annotated[int | None, Query(description="Filter by tag id")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[Product]:
    """Return a page of canonical products matching the search + filters."""
    result = xano.search_products(
        text=search,
        brand=brand,
        category=category,
        supplier=supplier,
        season=season,
        tag=tag,
        status=status,
        page=page,
        per_page=per_page,
    )
    total_pages = (result.total + per_page - 1) // per_page if per_page else 0
    return PaginatedResponse(
        items=result.items,
        total=result.total,
        page=page,
        page_size=per_page,
        total_pages=total_pages,
    )


@router.get("/{product_id}", response_model=Product)
def read_product(product_id: int, xano: XanoDep) -> Product:
    """Return one product's full detail from the Tillin catalog."""
    product = xano.get_product(product_id)
    if product is None:
        raise AppException(
            status_code=404, code="not_found", message="Product not found"
        )
    return product


@router.post("/{product_id}/images", response_model=ProductImagesUploadResult)
def upload_product_images(
    product_id: int,
    xano: XanoDep,
    files: Annotated[list[UploadFile], File(description="Image files to upload")],
) -> ProductImagesUploadResult:
    """Upload local/captured images to a product (proxied to Tillin storage).

    The browser posts the raw image bytes here; the backend forwards them to
    Tillin's bulk endpoint (multipart), which imports each into Xano storage and
    appends a `product_image` row. The Xano token never reaches the browser.
    """
    if not files:
        raise AppException(
            status_code=422, code="no_files", message="No image provided"
        )
    if len(files) > MAX_UPLOAD_FILES:
        raise AppException(
            status_code=422,
            code="too_many_files",
            message=f"Too many files (max {MAX_UPLOAD_FILES})",
        )
    parts: list[tuple[str, bytes, str]] = []
    for upload in files:
        data = upload.file.read()  # sync route -> threadpool; use the sync handle
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppException(
                status_code=422,
                code="file_too_large",
                message=f"{upload.filename or 'file'} exceeds the size limit",
            )
        parts.append(
            (
                upload.filename or "image.jpg",
                data,
                upload.content_type or "application/octet-stream",
            )
        )
    created = xano.upload_product_images(product_id, parts)
    return ProductImagesUploadResult(created=len(created), images=created)
