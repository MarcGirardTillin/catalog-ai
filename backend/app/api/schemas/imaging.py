"""Request/response schemas for the imaging routes (à-la-carte actions)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.product import ProductImage


class NormalizeOptions(BaseModel):
    """Options of POST /products/{id}/images/normalize (Photoroom)."""

    bg_color: str = "FFFFFF"
    output_size: str = "1600x2000"
    padding: str = "10%"
    format: str = "webp"
    quality: int = Field(default=80, ge=1, le=100)
    max_kb: int = Field(default=200, ge=1)


class NormalizeRequest(BaseModel):
    image_url: str
    # Tillin `product_image.id` of the source (enables replace-on-save).
    product_image_id: int | None = None
    options: NormalizeOptions | None = None


class GenerateModelOptions(BaseModel):
    """Options of POST /products/{id}/images/generate-model (FASHN)."""

    # Sans prompt, FASHN choisit librement le décor (vérifié live : scène
    # extérieure) — la décision actée est « porté mannequin sur fond uni ».
    prompt: str | None = "studio photo, plain light neutral background"
    aspect_ratio: str = "4:5"
    resolution: Literal["1k", "2k", "4k"] = "1k"
    generation_mode: Literal["fast", "balanced", "quality"] = "balanced"
    seed: int = 42
    num_images: int = Field(default=1, ge=1, le=4)


class GenerateModelRequest(BaseModel):
    image_url: str
    product_image_id: int | None = None
    options: GenerateModelOptions | None = None


class ImageAssetPublic(BaseModel):
    """One imaging operation: status + provenance + staged previews."""

    id: int
    product_id: int
    verb: str
    provider: str
    model: str | None = None
    seed: int | None = None
    status: str
    error: str | None = None
    # Authenticated preview routes (/imaging/assets/{id}/files/{i}), one per
    # staged file — empty until the operation completes.
    preview_urls: list[str] = Field(default_factory=list)
    source_image: str | None = None
    source_product_image_id: int | None = None
    created_at: datetime
    finished_at: datetime | None = None


class AssetSaveRequest(BaseModel):
    """POST /imaging/assets/{id}/save body."""

    # Also deactivate the original Tillin image (needs source_product_image_id).
    replace: bool = False


class AssetSaveResult(BaseModel):
    """Outcome of pushing a completed asset to Tillin (Xano bulk upload)."""

    created: int
    deactivated: int
    images: list[ProductImage] = Field(default_factory=list)
