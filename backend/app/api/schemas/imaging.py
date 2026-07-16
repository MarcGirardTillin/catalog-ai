"""Request/response schemas for the imaging routes (à-la-carte actions)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.product import ProductImage

RatioOption = Literal["4:5", "1:1", "3:4", "16:9", "original"]
FormatOption = Literal["webp", "jpeg", "jpg", "png"]


class NormalizeOptions(BaseModel):
    """Options of POST /products/{id}/images/normalize (segment + Pillow).

    Every treatment is à la carte: cutout (the only billed step), solid
    background, canvas ratio, centering, export format and compression.
    """

    remove_bg: bool = True
    bg_color: str = Field(default="FFFFFF", pattern=r"^#?[0-9a-fA-F]{6}$")
    ratio: RatioOption = "4:5"
    center: bool = True
    # Marge autour du produit, en POURCENTAGE du canevas (0 = bord à bord).
    margin_percent: float = Field(default=0.0, ge=0, le=45)
    format: FormatOption = "webp"
    quality: int = Field(default=80, ge=1, le=100)
    max_kb: int = Field(default=300, ge=1)


class NormalizeRequest(BaseModel):
    image_url: str
    # Tillin `product_image.id` of the source (enables replace-on-save).
    product_image_id: int | None = None
    options: NormalizeOptions | None = None


class GenerateModelOptions(BaseModel):
    """Options of POST /products/{id}/images/generate-model (FASHN).

    The instruction is resolved server-side: explicit `prompt` wins, else it
    is composed from framing/scene/instructions — each falling back to the
    account's generation settings. (Without a prompt FASHN picks a free
    environment — confirmed live: outdoor scene.)
    """

    prompt: str | None = None
    framing: Literal["full_body", "cropped_head"] | None = None
    scene: Literal["studio", "lifestyle"] | None = None
    instructions: str | None = None
    aspect_ratio: str = "4:5"
    resolution: Literal["1k", "2k", "4k"] = "1k"
    generation_mode: Literal["fast", "balanced", "quality"] = "balanced"
    seed: int = 42
    num_images: int = Field(default=1, ge=1, le=4)


class GenerateModelRequest(BaseModel):
    image_url: str
    product_image_id: int | None = None
    options: GenerateModelOptions | None = None


class StagedFilePublic(BaseModel):
    """Metadata of one staged OUTPUT file (weight/dimensions display)."""

    index: int
    size_bytes: int | None = None  # None on legacy assets (pre-metadata)
    width: int | None = None
    height: int | None = None
    format: str | None = None


class CropBox(BaseModel):
    """Recadrage du canevas composé, en pixels canevas (verrouillé au ratio
    côté UI pour que la sortie garde les proportions du format)."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


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
    # staged file — empty until the operation completes. A `?r={rev}` suffix
    # busts caches after a re-render.
    preview_urls: list[str] = Field(default_factory=list)
    # Output files metadata (aligned with preview_urls indexes).
    files: list[StagedFilePublic] = Field(default_factory=list)
    # Source image characteristics (when the pipeline probed it).
    source_size_bytes: int | None = None
    source_width: int | None = None
    source_height: int | None = None
    # True when a staged cutout/source allows POST /render (reposition, new
    # options) without a new provider call.
    can_render: bool = False
    # True once the asset was pushed to Tillin (history: « Enregistrée »).
    saved: bool = False
    # Last applied reposition (POST /render) — lets the studio rehydrate the
    # drag state without jumping back to the origin on the next render.
    render_offset_x: int = 0
    render_offset_y: int = 0
    render_scale: float = 1.0
    # Dernier recadrage appliqué (POST /render), pour réhydrater l'UI.
    render_crop: CropBox | None = None
    source_image: str | None = None
    source_product_image_id: int | None = None
    created_at: datetime
    finished_at: datetime | None = None


class PendingImagingProducts(BaseModel):
    """Products with at least one completed, unsaved asset (catalog badge)."""

    product_ids: list[int] = Field(default_factory=list)


class RenderRequest(BaseModel):
    """POST /imaging/assets/{id}/render body — local Pillow recompose.

    Offsets are canvas pixels, scale multiplies the fitted size. Any other
    field left to None keeps the option the asset was produced with.
    """

    offset_x: int = Field(default=0, ge=-4000, le=4000)
    offset_y: int = Field(default=0, ge=-4000, le=4000)
    scale: float = Field(default=1.0, gt=0, le=4)
    # Recadrage final du canevas (px canevas) ; None = pas de recadrage.
    crop: CropBox | None = None
    bg_color: str | None = Field(default=None, pattern=r"^#?[0-9a-fA-F]{6}$")
    ratio: RatioOption | None = None
    center: bool | None = None
    format: FormatOption | None = None
    quality: int | None = Field(default=None, ge=1, le=100)
    max_kb: int | None = Field(default=None, ge=1)


class AssetSaveRequest(BaseModel):
    """POST /imaging/assets/{id}/save body."""

    # Also deactivate the original Tillin image (needs source_product_image_id).
    replace: bool = False
    # Optional custom filenames aligned with the output indexes (None entries
    # fall back to the default naming); slugged server-side, extension imposed.
    filenames: list[str | None] | None = None


class AssetSaveResult(BaseModel):
    """Outcome of pushing a completed asset to Tillin (Xano bulk upload)."""

    created: int
    deactivated: int
    images: list[ProductImage] = Field(default_factory=list)
