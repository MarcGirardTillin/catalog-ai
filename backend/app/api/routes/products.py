"""Product selection route — reads the Tillin catalog through Xano.

This is the Phase 0 read path: pick products by ``tag`` or by explicit ``ids``
so an enrichment job can later be built from the selection.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import XanoDep, get_current_user
from app.api.exceptions import AppException
from app.api.schemas import PaginatedResponse, Product

router = APIRouter(
    prefix="/products",
    tags=["products"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=PaginatedResponse[Product])
def list_products(
    xano: XanoDep,
    tag: Annotated[str | None, Query(description="Select products by tag")] = None,
    ids: Annotated[
        list[int] | None, Query(description="Select products by id (repeatable)")
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[Product]:
    """Return a page of canonical products selected by tag or by ids."""
    if (tag is None) == (not ids):
        raise AppException(
            status_code=400,
            code="invalid_selection",
            message="Provide exactly one of 'tag' or 'ids'",
        )

    result = xano.list_products(tag=tag, ids=ids, page=page, per_page=per_page)
    total_pages = (result.total + per_page - 1) // per_page if per_page else 0
    return PaginatedResponse(
        items=result.items,
        total=result.total,
        page=page,
        page_size=per_page,
        total_pages=total_pages,
    )
