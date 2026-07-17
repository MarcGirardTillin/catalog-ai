"""Request/response schemas for the imaging routes (à-la-carte actions)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.product import ProductImage

RatioOption = Literal["4:5", "1:1", "3:4", "16:9", "original"]
FormatOption = Literal["webp", "jpeg", "jpg", "png"]
# Orientation du mannequin généré ; None = laissée libre (défaut).
PoseOption = Literal[
    "face",
    "back",
    "profile_left",
    "profile_right",
    "three_quarter_left",
    "three_quarter_right",
]
# Moteur du verbe « porté mannequin » : FASHN (historique) ou Photoroom
# Virtual Model. None = réglage du compte (imaging_generation_engine).
EngineOption = Literal["fashn", "photoroom"]
# Presets natifs Photoroom Virtual Model (mannequins et décors).
ModelPresetOption = Literal[
    "avery",
    "sam",
    "taylor",
    "kendall",
    "jordan",
    "casey",
    "maya",
    "reece",
    "lena",
    "julia",
    "jackson",
    "sophia",
    "emma",
    "ava",
    "zoe",
    "fiona",
]
ScenePresetOption = Literal[
    "random",
    "street",
    "bedroom",
    "sunset",
    "factory",
    "studio",
    "coloredstudio",
    "concretestudio",
    "beach",
    "tropical",
    "library",
    "forest",
    "businessdistrict",
    "countryside",
    "flowers",
    "goldenlight",
    "mountain",
    "pool",
    "latincity",
    "cafe",
    "asiancity",
    "nightlights",
    "desert",
]
# Poses natives Photoroom (remplacent PoseOption quand engine=photoroom).
PhotoroomPoseOption = Literal[
    "random",
    "standing",
    "34turn",
    "powerstance",
    "walkingforward",
    "handinpocket",
    "crossedarms",
    "back",
    "overtheshoulder",
    "seated",
    "adjustingclothing",
    "playfulspin",
]


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
    # Orientation du mannequin (face/dos/profil/trois-quarts) ; None = libre.
    pose: PoseOption | None = None
    instructions: str | None = None
    aspect_ratio: str = "4:5"
    resolution: Literal["1k", "2k", "4k"] = "1k"
    generation_mode: Literal["fast", "balanced", "quality"] = "balanced"
    seed: int = 42
    num_images: int = Field(default=1, ge=1, le=4)
    # Moteur : None = défaut du compte. Les champs suivants sont
    # Photoroom-only (ignorés côté FASHN) ; resolution/generation_mode/seed/
    # num_images sont FASHN-only (forcés à 1/None côté Photoroom).
    engine: EngineOption | None = None
    model_preset: ModelPresetOption | None = None
    scene_preset: ScenePresetOption | None = None
    photoroom_pose: PhotoroomPoseOption | None = None


class GenerateModelRequest(BaseModel):
    image_url: str
    product_image_id: int | None = None
    options: GenerateModelOptions | None = None
    # URLs publiques Tillin des autres vues du produit (Photoroom only).
    additional_image_urls: list[str] | None = Field(default=None, max_length=3)


class GenerateFlatOptions(BaseModel):
    """Options communes aux verbes flat lay et ghost mannequin (Photoroom)."""

    prompt: str | None = Field(default=None, max_length=500)
    ratio: RatioOption = "4:5"


class GenerateFlatRequest(BaseModel):
    image_url: str
    product_image_id: int | None = None
    options: GenerateFlatOptions | None = None


class FinalizeRequest(BaseModel):
    """POST /imaging/assets/{id}/finalize — retouches IA « cuites » (payant).

    Un appel /v2/edit = un débit, quelles que soient les options combinées.
    Au moins une option doit être active (422 nothing_to_finalize sinon,
    vérifié dans la route pour un code d'erreur métier explicite).
    """

    shadow_mode: Literal["soft", "hard", "floating"] | None = None
    shadow_intensity: float | None = Field(default=None, ge=0, le=1)
    # Décor IA généré par prompt ; prioritaire sur la couleur conservée.
    background_prompt: str | None = Field(default=None, max_length=500)
    ironing: bool = False
    upscale_factor: Literal[2, 4] | None = None
    beautify: bool = False
    # Recoloration du vêtement (via Edit With AI, gabarit serveur).
    recolor_prompt: str | None = Field(default=None, max_length=200)

    def has_active_option(self) -> bool:
        return bool(
            self.shadow_mode
            or (self.background_prompt and self.background_prompt.strip())
            or self.ironing
            or self.upscale_factor
            or self.beautify
            or (self.recolor_prompt and self.recolor_prompt.strip())
        )


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
    # True quand une finalisation IA a été appliquée (retouches « cuites ») ;
    # un re-render local recompose depuis le cutout et EFFACE ce flag.
    finalized: bool = False
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
