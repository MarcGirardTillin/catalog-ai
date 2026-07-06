"""Product selection route — searches the Tillin catalog through Xano.

Backs the CatalogAI selection screen: free-text search + filters over the
Tillin catalog so the user can pick product ids, then build an enrichment job
from that selection. The Xano bearer token never reaches the browser — the
backend proxies the call behind the session cookie.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import XanoDep, get_current_user
from app.api.schemas import PaginatedResponse, Product

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
