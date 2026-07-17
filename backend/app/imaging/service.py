"""Business verbs of the imaging service (the stable internal API).

Each verb hides its provider behind an interchangeable adapter and emits
`usage_event` rows through :func:`record_usage` (metering is mandatory at the
wrapper level; pipelines stay metering-agnostic). Like the rest of the usage
layer, the verbs do NOT commit — the caller owns the transaction so usage and
results land atomically.

Normalization is a two-step pipeline since 2026-07-12: Photoroom `/v1/segment`
(cutout RGBA, 0.02 $/image) + local Pillow composition (`app.imaging.compose`)
for canvas/bg/centering/compression — every geometric option is ours, so a
re-render (new options, manual reposition) never re-bills the provider.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.api.services.usage import record_usage
from app.clients.base import ExternalServiceError
from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient
from app.imaging.compose import compose, probe

FASHN_PRODUCT_TO_MODEL = "product-to-model"
PHOTOROOM_MODEL = "photoroom-v2"  # legacy /v2/edit (kept for old traces)
PHOTOROOM_SEGMENT_MODEL = "photoroom-segment-v1"
# Nouveaux appels /v2/edit (flat lay, ghost mannequin, virtual model,
# finalisation IA) — 0,10 $/image quel que soit le nombre d'options.
PHOTOROOM_EDIT_MODEL = "photoroom-edit-v2"

# Ratio app -> preset `size` Photoroom (flatLay/ghostMannequin/virtualModel).
# 4:5 n'a pas de preset exact : PORTRAIT_HD_4_3 est le plus proche (valeurs
# à confirmer en sandbox ; repli outputSize=WxH si un preset est rejeté).
PHOTOROOM_SIZE_PRESETS = {
    "4:5": "PORTRAIT_HD_4_3",
    "3:4": "PORTRAIT_HD_4_3",
    "1:1": "SQUARE_HD",
    "16:9": "LANDSCAPE_HD_16_9",
}

# Source download guards — the verb fetches the image itself: segment wants
# multipart bytes, and the source weight/dims are part of the outcome.
SOURCE_TIMEOUT = 30.0
SOURCE_MAX_BYTES = 30 * 1024 * 1024

# FASHN credits per image: resolution -> generation_mode -> credits.
FASHN_CREDITS: dict[str, dict[str, int]] = {
    "1k": {"fast": 1, "balanced": 2, "quality": 3},
    "2k": {"fast": 2, "balanced": 3, "quality": 4},
    "4k": {"fast": 3, "balanced": 4, "quality": 5},
}


@dataclass
class NormalizeOptions:
    """Options of the deterministic verb (segment + local compose).

    Every step is opt-out (à la carte): `remove_bg` gates the only provider
    call; `offset_x/offset_y/scale` are the manual-repositioning knobs (used
    by re-renders, 0/0/1.0 on a first pass).
    """

    remove_bg: bool = True
    bg_color: str = "FFFFFF"
    ratio: str = "4:5"
    center: bool = True
    # Marge autour du produit, fraction du canevas (0.10 = 10 %). Décision
    # Marc 2026-07-16 : AUCUNE marge par défaut ; configurable par compte
    # (imaging_margin_percent, saisi en %) et par appel.
    margin_pct: float = 0.0
    fmt: str = "webp"
    quality: int = 80
    max_kb: int = 300
    offset_x: int = 0
    offset_y: int = 0
    scale: float = 1.0


# Instruction (prompt) building blocks for the generative verb: the client's
# framing/scene settings + free-form directives compose the FASHN prompt.
FRAMING_PROMPTS = {
    "full_body": "full body shot, the model fully visible",
    "cropped_head": "framed from the neck down, the model's head cropped out of frame",
}
SCENE_PROMPTS = {
    "studio": "studio photo, plain light neutral background",
    "lifestyle": "lifestyle photo, natural in-context setting",
}
# Orientation du mannequin (optionnelle) : vide = FASHN choisit librement.
POSE_PROMPTS = {
    "face": "the model facing the camera straight on",
    "back": "the model seen from behind",
    "profile_left": "left side profile view of the model",
    "profile_right": "right side profile view of the model",
    "three_quarter_left": "three-quarter view, the model turned slightly to their left",
    "three_quarter_right": (
        "three-quarter view, the model turned slightly to their right"
    ),
}


def build_generation_prompt(
    framing: str, scene: str, instructions: str | None, pose: str | None = None
) -> str:
    """Compose the FASHN instruction from the structured config + free text.

    Unknown values fall back to the historical default (studio, full body) —
    without a prompt FASHN picks a free environment (confirmed live: outdoor
    scene), which is never what a boutique wants by default. `pose` is the
    only OPTIONAL block: absent or unknown → nothing added (free orientation).
    """
    parts = [
        SCENE_PROMPTS.get(scene, SCENE_PROMPTS["studio"]),
        FRAMING_PROMPTS.get(framing, FRAMING_PROMPTS["full_body"]),
    ]
    if pose and pose in POSE_PROMPTS:
        parts.append(POSE_PROMPTS[pose])
    if instructions and instructions.strip():
        parts.append(instructions.strip())
    return ", ".join(parts)


@dataclass
class GenerateModelOptions:
    """Options of the generative verb (FASHN `product-to-model`).

    Without a prompt FASHN picks a free environment (confirmed live: outdoor
    scene) — the locked decision is "worn by a model on a plain background",
    hence the default prompt (callers usually pass one built by
    :func:`build_generation_prompt` from the account settings).
    """

    prompt: str | None = "studio photo, plain light neutral background"
    aspect_ratio: str = "4:5"
    resolution: str = "1k"
    generation_mode: str = "balanced"
    seed: int = 42
    num_images: int = 1
    output_format: str = "jpeg"


# Pose FASHN (nos réglages) -> preset pose Photoroom Virtual Model. Les
# profils stricts n'ont pas d'équivalent : l'UI affiche les poses Photoroom
# quand le moteur est photoroom, ce mapping ne sert qu'au défaut de compte.
PHOTOROOM_POSE_MAP = {
    "face": "standing",
    "back": "back",
    "three_quarter_left": "34turn",
    "three_quarter_right": "34turn",
}
# Poses natives Photoroom acceptées telles quelles (validation côté schéma).
PHOTOROOM_POSES = {
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
}
# Scène de nos réglages -> preset décor Photoroom (sauf preset explicite).
PHOTOROOM_SCENE_MAP = {"studio": "studio", "lifestyle": "random"}


@dataclass
class GenerateFlatOptions:
    """Options des verbes flat lay / ghost mannequin (Photoroom /v2/edit)."""

    prompt: str | None = None  # style libre (ex. « fond lin clair »)
    ratio: str = "4:5"


@dataclass
class GenerateVirtualModelOptions:
    """Options du moteur Photoroom Virtual Model (porté mannequin)."""

    prompt: str | None = None  # style libre (directives, cadrage)
    model_preset: str | None = None  # avery…fiona ; None = Photoroom choisit
    scene_preset: str | None = None  # studio…desert ; None = dérivé de scene
    pose: str | None = None  # preset Photoroom ; None = libre
    ratio: str = "4:5"
    additional_image_urls: list[str] = field(default_factory=list)  # max 3


@dataclass
class FinalizeOptions:
    """Options de la finalisation IA (un appel /v2/edit = un débit).

    Toutes optionnelles ; le caller garantit qu'au moins une est active.
    L'image d'entrée est la recomposition RGBA transparente du positionnement
    validé : Photoroom pose l'ombre sur l'alpha puis remplit le fond.
    """

    shadow_mode: str | None = None  # "soft" | "hard" | "floating"
    shadow_intensity: float | None = None  # 0-1
    background_color: str | None = None  # hex — fond conservé
    background_prompt: str | None = None  # décor IA (prioritaire sur color)
    ironing: bool = False
    upscale_factor: int | None = None  # 2 | 4
    beautify: bool = False
    recolor_prompt: str | None = None  # nouvelle couleur du vêtement
    # Repli sans cutout stagé (remove_bg désactivé à la normalisation) :
    # l'image envoyée est opaque, Photoroom re-détoure lui-même.
    remove_background: bool = False
    output_format: str = "png"


@dataclass
class ImagingResult:
    """One produced image + its systematic provenance trace."""

    data: bytes
    width: int | None
    height: int | None
    format: str
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceInfo:
    """The downloaded source image and its probed characteristics."""

    data: bytes
    width: int
    height: int
    format: str


@dataclass
class NormalizeOutcome:
    """Everything a caller may want to stage after a normalization.

    `cutout` (RGBA PNG) is what re-renders recompose from — staging it means
    repositioning never pays Photoroom again. None when `remove_bg` was off.
    """

    output: ImagingResult
    cutout: bytes | None
    source: SourceInfo


def fashn_credits(resolution: str, generation_mode: str, num_images: int) -> int:
    """Static credits grid (FASHN does not report consumption in /status)."""
    per_image = FASHN_CREDITS.get(resolution, {}).get(generation_mode)
    if per_image is None:
        raise ValueError(
            f"unknown FASHN pricing for resolution={resolution!r} "
            f"mode={generation_mode!r}"
        )
    return per_image * num_images


def _download_source(url: str) -> bytes:
    """Fetch the source image (30 s timeout, 30 MB cap, redirects followed)."""
    try:
        response = httpx.get(url, timeout=SOURCE_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise ExternalServiceError(
            "source_image", "Source image is unreachable"
        ) from exc
    if response.status_code >= 400:
        raise ExternalServiceError(
            "source_image",
            "Source image returned an error",
            detail={"upstream_status": response.status_code},
        )
    if len(response.content) > SOURCE_MAX_BYTES:
        raise ExternalServiceError(
            "source_image", "Source image is too large", status_code=422
        )
    return response.content


def normalize_product_image(
    src: bytes | str,
    *,
    options: NormalizeOptions | None = None,
    photoroom: PhotoroomClient,
    db: Session,
    account_id: int,
    job_id: int | None = None,
    item_id: int | None = None,
) -> NormalizeOutcome:
    """Deterministic pipeline: segment cutout (opt-out) + local Pillow compose.

    `src` is the source image URL or its raw bytes. Only the cutout step bills
    Photoroom (one usage_event per image); with `remove_bg=False` the pipeline
    is fully local and meters nothing.

    `job_id`/`item_id` attach the metered usage_event to an enrichment run
    when the verb is called from the batch pipeline (None for à la carte).
    """
    options = options or NormalizeOptions()
    data = src if isinstance(src, bytes) else _download_source(src)
    try:
        src_width, src_height, src_format = probe(data)
    except Exception as exc:
        raise ExternalServiceError(
            "source_image", "Source is not a readable image", status_code=422
        ) from exc

    cutout: bytes | None = None
    if options.remove_bg:
        cutout = photoroom.remove_background(data)
        record_usage(
            db,
            account_id=account_id,
            source="imaging",
            provider="photoroom",
            metric="images",
            quantity=1,
            job_id=job_id,
            item_id=item_id,
            model=PHOTOROOM_SEGMENT_MODEL,
        )

    composed = compose(
        cutout if cutout is not None else data,
        has_alpha=cutout is not None,
        bg_color=options.bg_color,
        ratio=options.ratio,
        center=options.center,
        margin_pct=options.margin_pct,
        offset_x=options.offset_x,
        offset_y=options.offset_y,
        scale=options.scale,
        fmt=options.fmt,
        quality=options.quality,
        max_kb=options.max_kb,
    )
    output = ImagingResult(
        data=composed.data,
        width=composed.width,
        height=composed.height,
        format=composed.format,
        trace={
            "provider": "photoroom" if options.remove_bg else "local",
            "model": PHOTOROOM_SEGMENT_MODEL if options.remove_bg else None,
            "steps": (["remove_bg"] if options.remove_bg else []) + ["compose"],
            "params": asdict(options),
        },
    )
    return NormalizeOutcome(
        output=output,
        cutout=cutout,
        source=SourceInfo(
            data=data, width=src_width, height=src_height, format=src_format
        ),
    )


def generate_model_photo(
    product_image: str,
    *,
    options: GenerateModelOptions | None = None,
    fashn: FashnClient,
    db: Session,
    account_id: int,
) -> list[ImagingResult]:
    """Generative pipeline: packshot -> worn by a model (FASHN)."""
    options = options or GenerateModelOptions()
    inputs: dict[str, Any] = {
        "product_image": product_image,
        "aspect_ratio": options.aspect_ratio,
        "resolution": options.resolution,
        "generation_mode": options.generation_mode,
        "seed": options.seed,
        "num_images": options.num_images,
        "output_format": options.output_format,
    }
    if options.prompt is not None:
        inputs["prompt"] = options.prompt
    params = {k: v for k, v in inputs.items() if k != "product_image"}

    prediction_id = fashn.run(FASHN_PRODUCT_TO_MODEL, inputs)
    urls = fashn.wait(prediction_id)
    results = [
        ImagingResult(
            data=fashn.download(url),
            width=None,
            height=None,
            format=options.output_format,
            trace={
                "provider": "fashn",
                "model": FASHN_PRODUCT_TO_MODEL,
                "seed": options.seed,
                "params": params,
            },
        )
        for url in urls
    ]
    record_usage(
        db,
        account_id=account_id,
        source="imaging",
        provider="fashn",
        metric="credits",
        quantity=fashn_credits(
            options.resolution, options.generation_mode, options.num_images
        ),
        model=FASHN_PRODUCT_TO_MODEL,
    )
    return results


def _photoroom_size(ratio: str) -> str | None:
    return PHOTOROOM_SIZE_PRESETS.get(ratio)


def _run_photoroom_edit(
    params: dict[str, Any],
    *,
    image_url: str,
    photoroom: PhotoroomClient,
    db: Session,
    account_id: int,
    trace_params: dict[str, Any],
) -> list[ImagingResult]:
    """Appel /v2/edit commun aux verbes génératifs (GET, URL publique Tillin) :
    une image en retour, un usage_event photoroom-edit-v2. Ne commit pas."""
    data = photoroom.edit(params, image_url=image_url)
    try:
        width, height, fmt = probe(data)
    except Exception:  # trace best effort — l'image est retournée telle quelle
        width, height, fmt = None, None, "png"
    record_usage(
        db,
        account_id=account_id,
        source="imaging",
        provider="photoroom",
        metric="images",
        quantity=1,
        model=PHOTOROOM_EDIT_MODEL,
    )
    return [
        ImagingResult(
            data=data,
            width=width,
            height=height,
            format=fmt,
            trace={
                "provider": "photoroom",
                "model": PHOTOROOM_EDIT_MODEL,
                "params": trace_params,
            },
        )
    ]


def generate_flat_photo(
    product_image: str,
    *,
    options: GenerateFlatOptions | None = None,
    photoroom: PhotoroomClient,
    db: Session,
    account_id: int,
) -> list[ImagingResult]:
    """Photo produit -> mise à plat stylisée (Photoroom flat lay)."""
    options = options or GenerateFlatOptions()
    params: dict[str, Any] = {"flatLay": {"mode": "ai.auto"}}
    if options.prompt and options.prompt.strip():
        params["flatLay"]["prompt"] = options.prompt.strip()
    if size := _photoroom_size(options.ratio):
        params["flatLay"]["size"] = size
    return _run_photoroom_edit(
        params,
        image_url=product_image,
        photoroom=photoroom,
        db=db,
        account_id=account_id,
        trace_params={"verb": "flat_lay", **asdict(options)},
    )


def generate_ghost_photo(
    product_image: str,
    *,
    options: GenerateFlatOptions | None = None,
    photoroom: PhotoroomClient,
    db: Session,
    account_id: int,
) -> list[ImagingResult]:
    """Photo portée/mannequin -> effet mannequin invisible (ghost mannequin)."""
    options = options or GenerateFlatOptions()
    params: dict[str, Any] = {"ghostMannequin": {"mode": "ai.auto"}}
    if options.prompt and options.prompt.strip():
        params["ghostMannequin"]["prompt"] = options.prompt.strip()
    if size := _photoroom_size(options.ratio):
        params["ghostMannequin"]["size"] = size
    return _run_photoroom_edit(
        params,
        image_url=product_image,
        photoroom=photoroom,
        db=db,
        account_id=account_id,
        trace_params={"verb": "ghost_mannequin", **asdict(options)},
    )


def generate_virtual_model_photo(
    product_image: str,
    *,
    options: GenerateVirtualModelOptions | None = None,
    photoroom: PhotoroomClient,
    db: Session,
    account_id: int,
) -> list[ImagingResult]:
    """Photo produit -> portée par un mannequin virtuel (Photoroom).

    2e moteur du verbe « porté mannequin » à côté de FASHN : presets natifs
    (mannequin, décor, pose), multi-vues du produit, prompt de style libre.
    """
    options = options or GenerateVirtualModelOptions()
    virtual: dict[str, Any] = {"mode": "ai.auto"}
    if options.model_preset:
        virtual["model"] = {"preset": {"name": options.model_preset}}
    if options.pose and options.pose in PHOTOROOM_POSES:
        virtual["pose"] = options.pose
    if options.prompt and options.prompt.strip():
        virtual["prompt"] = options.prompt.strip()
    if options.additional_image_urls:
        virtual["additionalProductImages"] = [
            {"imageUrl": url} for url in options.additional_image_urls[:3]
        ]
    if size := _photoroom_size(options.ratio):
        virtual["size"] = size
    params: dict[str, Any] = {"virtualModel": virtual}
    if options.scene_preset:
        params["virtualModel"]["scene"] = {"preset": {"name": options.scene_preset}}
    trace_options = asdict(options)
    return _run_photoroom_edit(
        params,
        image_url=product_image,
        photoroom=photoroom,
        db=db,
        account_id=account_id,
        trace_params={"verb": "virtual_model", **trace_options},
    )


def finalize_image(
    image_bytes: bytes,
    *,
    options: FinalizeOptions,
    photoroom: PhotoroomClient,
    db: Session,
    account_id: int,
) -> ImagingResult:
    """Finalisation IA d'une normalisation positionnée (un appel = un débit).

    `image_bytes` = recomposition RGBA transparente du positionnement validé
    (POST multipart — le staging n'est pas public). Photoroom applique les
    options « cuites » (ombre, décor, défroissage, upscale, beautifier,
    recoloration) et remplit le fond.
    """
    params: dict[str, Any] = {}
    if options.shadow_mode:
        params["shadow"] = {"mode": f"ai.{options.shadow_mode}"}
        if options.shadow_intensity is not None:
            params["shadow"]["intensityOverride"] = options.shadow_intensity
    if options.background_prompt and options.background_prompt.strip():
        params["background"] = {"prompt": options.background_prompt.strip()}
    elif options.background_color:
        params["background"] = {"color": options.background_color.lstrip("#")}
    if options.ironing:
        params["ironing"] = {"mode": "ai.auto"}
    if options.upscale_factor:
        params["upscale"] = {"mode": "ai.auto", "factor": options.upscale_factor}
    if options.beautify:
        params["beautify"] = {"mode": "ai.auto"}
    if options.recolor_prompt and options.recolor_prompt.strip():
        # Pas de namespace recolor.* dans /v2/edit : la recoloration passe par
        # Edit With AI en langage naturel (gabarit vérifié en sandbox).
        params["editWithAI"] = {
            "mode": "ai.auto",
            "prompt": (
                f"Change the color of the garment to {options.recolor_prompt.strip()}"
            ),
        }
    if not params:
        raise ValueError("finalize_image requires at least one active option")
    if options.remove_background:
        params["removeBackground"] = True
    params["export"] = {"format": options.output_format}

    data = photoroom.edit(params, image_bytes=image_bytes)
    try:
        width, height, fmt = probe(data)
    except Exception:
        width, height, fmt = None, None, options.output_format
    record_usage(
        db,
        account_id=account_id,
        source="imaging",
        provider="photoroom",
        metric="images",
        quantity=1,
        model=PHOTOROOM_EDIT_MODEL,
    )
    return ImagingResult(
        data=data,
        width=width,
        height=height,
        format=fmt,
        trace={
            "provider": "photoroom",
            "model": PHOTOROOM_EDIT_MODEL,
            "params": {"verb": "finalize", **asdict(options)},
        },
    )
