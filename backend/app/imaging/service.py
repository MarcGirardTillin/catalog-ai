"""Business verbs of the imaging service (the stable internal API).

Each verb hides its provider behind an interchangeable adapter and emits
`usage_event` rows through :func:`record_usage` (metering is mandatory at the
wrapper level; pipelines stay metering-agnostic). Like the rest of the usage
layer, the verbs do NOT commit — the caller owns the transaction so usage and
results land atomically.

Note on dimensions: Pillow is not a backend dependency (checked pyproject), so
`ImagingResult.width/height` stay None for now — adding Pillow is a separate
decision (the `local` provider will need it).
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.api.services.usage import record_usage
from app.clients.fashn import FashnClient
from app.clients.photoroom import PhotoroomClient

FASHN_PRODUCT_TO_MODEL = "product-to-model"
PHOTOROOM_MODEL = "photoroom-v2"

# FASHN credits per image: resolution -> generation_mode -> credits.
FASHN_CREDITS: dict[str, dict[str, int]] = {
    "1k": {"fast": 1, "balanced": 2, "quality": 3},
    "2k": {"fast": 2, "balanced": 3, "quality": 4},
    "4k": {"fast": 3, "balanced": 4, "quality": 5},
}


@dataclass
class NormalizeOptions:
    """Options of the deterministic verb (Photoroom)."""

    bg_color: str = "FFFFFF"
    ratio: str = "4:5"
    output_size: str = "1600x2000"
    padding: str = "10%"
    fmt: str = "webp"
    quality: int = 80
    max_kb: int = 200


@dataclass
class GenerateModelOptions:
    """Options of the generative verb (FASHN `product-to-model`)."""

    prompt: str | None = None
    aspect_ratio: str = "4:5"
    resolution: str = "1k"
    generation_mode: str = "balanced"
    seed: int = 42
    num_images: int = 1
    output_format: str = "jpeg"


@dataclass
class ImagingResult:
    """One produced image + its systematic provenance trace."""

    data: bytes
    width: int | None
    height: int | None
    format: str
    trace: dict[str, Any] = field(default_factory=dict)


def fashn_credits(resolution: str, generation_mode: str, num_images: int) -> int:
    """Static credits grid (FASHN does not report consumption in /status)."""
    per_image = FASHN_CREDITS.get(resolution, {}).get(generation_mode)
    if per_image is None:
        raise ValueError(
            f"unknown FASHN pricing for resolution={resolution!r} "
            f"mode={generation_mode!r}"
        )
    return per_image * num_images


def normalize_product_image(
    src: bytes | str,
    *,
    options: NormalizeOptions | None = None,
    photoroom: PhotoroomClient,
    db: Session,
    account_id: int,
) -> ImagingResult:
    """Deterministic pipeline: cutout + solid bg + pad to 4:5 + format/weight.

    `src` is the source image URL; raw bytes are not supported yet (whether
    Photoroom v2 accepts multipart input is an open item to confirm live, like
    the v2 parameter names).
    """
    if isinstance(src, bytes):
        raise NotImplementedError(
            "normalize_product_image only accepts a source URL for now "
            "(Photoroom v2 multipart input is unconfirmed)"
        )
    options = options or NormalizeOptions()
    data = photoroom.edit_image(
        src,
        background_color=options.bg_color,
        output_size=options.output_size,
        padding=options.padding,
        export_format=options.fmt,
        quality=options.quality,
    )
    record_usage(
        db,
        account_id=account_id,
        source="imaging",
        provider="photoroom",
        metric="images",
        quantity=1,
        model=PHOTOROOM_MODEL,
    )
    return ImagingResult(
        data=data,
        width=None,
        height=None,
        format=options.fmt,
        trace={
            "provider": "photoroom",
            "model": PHOTOROOM_MODEL,
            "params": {
                "bg_color": options.bg_color,
                "ratio": options.ratio,
                "output_size": options.output_size,
                "padding": options.padding,
                "format": options.fmt,
                "quality": options.quality,
                "max_kb": options.max_kb,
            },
        },
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


def generate_flat_photo() -> list[ImagingResult]:
    """Worn -> flat packshot. Reserved: no confirmed FASHN endpoint yet."""
    raise NotImplementedError(
        "generate_flat_photo is deferred: no suitable FASHN endpoint is "
        "available yet (reserved in the interface, see plan)"
    )
