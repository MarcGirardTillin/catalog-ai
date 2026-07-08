"""Request/response schemas for the brands screen (reference websites)."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

WebsiteUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class BrandPublic(BaseModel):
    """A Tillin brand with its reference website URLs."""

    id: int
    name: str | None = None
    website_urls: list[str] = Field(default_factory=list)


class BrandWebsiteUrlsUpdate(BaseModel):
    """Replace a brand's reference website URLs."""

    website_urls: list[WebsiteUrl] = Field(max_length=20)
