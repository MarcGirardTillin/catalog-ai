"""Brand routes — consult and edit the brands' reference websites.

The resolver searches a brand's `website_urls` when looking for source product
pages, so keeping them accurate directly improves enrichment quality. Reads and
writes go through the shared Xano client (the bearer token never reaches the
browser).
"""

from fastapi import APIRouter, Depends

from app.api.deps import XanoDep, get_current_user
from app.api.schemas.brands import BrandPublic, BrandWebsiteUrlsUpdate
from app.clients.xano import normalize_website_urls

router = APIRouter(
    prefix="/brands",
    tags=["brands"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[BrandPublic])
def list_brands(xano: XanoDep) -> list[BrandPublic]:
    """Return every Tillin brand with its reference websites, sorted by name."""
    return [
        BrandPublic(id=brand.id, name=brand.name, website_urls=brand.website_urls)
        for brand in xano.list_brands()
        if brand.id is not None
    ]


@router.put("/{brand_id}/website_urls", response_model=BrandPublic)
def update_brand_website_urls(
    brand_id: int, payload: BrandWebsiteUrlsUpdate, xano: XanoDep
) -> BrandPublic:
    """Replace a brand's reference website URLs in Tillin."""
    normalized = normalize_website_urls(payload.website_urls)
    xano.set_brand_website_urls(brand_id, normalized)
    # Echo the normalized URLs actually sent (the upstream response shape is
    # unknown); the name is not re-read — the client already displays it.
    return BrandPublic(id=brand_id, website_urls=normalized)
