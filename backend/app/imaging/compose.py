"""Local Pillow composition: ratio canvas + solid bg + centering + compression.

Pure functions, no network/DB — the imaging verbs orchestrate, this module owns
all the geometry of the "normalize" verb. Because composition is local, a
re-render (new options, manual offset/scale) never needs a new provider call:
it just re-runs :func:`compose` on the staged cutout/source.
"""

import io
from dataclasses import dataclass

from PIL import Image

# Canvas ratios offered to the client; None = keep the input frame's ratio.
RATIOS: dict[str, tuple[int, int] | None] = {
    "4:5": (4, 5),
    "1:1": (1, 1),
    "3:4": (3, 4),
    "16:9": (16, 9),
    "original": None,
}

# Long-side pixel size of the output canvas (4:5 -> 1600x2000, the historical
# Photoroom output size). "original" frames larger than this are downscaled.
CANVAS_LONG_SIDE = 2000

# Alpha value above which a pixel counts as "product" for the centering
# bounding box — cutout noise (and the sandbox watermark) live below it.
ALPHA_BBOX_THRESHOLD = 8

# Compression loop (WebP/JPEG): decrement quality by this step down to the
# floor until the payload fits max_kb. PNG is lossless: optimize only.
QUALITY_STEP = 8
QUALITY_FLOOR = 40

# Requested format -> (normalized name, Pillow encoder name).
_FORMATS = {
    "webp": ("webp", "WEBP"),
    "jpeg": ("jpeg", "JPEG"),
    "jpg": ("jpeg", "JPEG"),
    "png": ("png", "PNG"),
}


@dataclass
class ComposedImage:
    """One encoded output + its real dimensions."""

    data: bytes
    width: int
    height: int
    format: str


def probe(data: bytes) -> tuple[int, int, str]:
    """(width, height, format) of an encoded image (format lowercased)."""
    with Image.open(io.BytesIO(data)) as img:
        return img.width, img.height, (img.format or "").lower()


def _parse_hex(bg_color: str) -> tuple[int, int, int]:
    value = bg_color.strip().lstrip("#")
    if len(value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(f"invalid background color {bg_color!r}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _canvas_size(ratio: str, frame_w: int, frame_h: int) -> tuple[int, int]:
    """Output canvas dimensions for a ratio, given the input frame size."""
    pair = RATIOS[ratio]
    if pair is None:  # "original": keep the frame's ratio, cap the long side
        long_side = max(frame_w, frame_h)
        factor = min(1.0, CANVAS_LONG_SIDE / long_side)
        return max(1, round(frame_w * factor)), max(1, round(frame_h * factor))
    rw, rh = pair
    if rw <= rh:
        return round(CANVAS_LONG_SIDE * rw / rh), CANVAS_LONG_SIDE
    return CANVAS_LONG_SIDE, round(CANVAS_LONG_SIDE * rh / rw)


def _encode(img: Image.Image, fmt: str, quality: int, max_kb: int | None) -> bytes:
    _, encoder = _FORMATS[fmt]
    if encoder == "PNG":  # lossless: max_kb is best effort
        buffer = io.BytesIO()
        img.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()
    current = quality
    while True:
        buffer = io.BytesIO()
        img.save(buffer, encoder, quality=current)
        data = buffer.getvalue()
        if max_kb is None or len(data) <= max_kb * 1024 or current <= QUALITY_FLOOR:
            return data
        current = max(QUALITY_FLOOR, current - QUALITY_STEP)


def compose(
    image: bytes,
    *,
    has_alpha: bool,
    bg_color: str = "FFFFFF",
    ratio: str = "4:5",
    center: bool = True,
    margin_pct: float = 0.10,
    offset_x: int = 0,
    offset_y: int = 0,
    scale: float = 1.0,
    fmt: str = "webp",
    quality: int = 80,
    max_kb: int | None = None,
) -> ComposedImage:
    """Compose the product onto a solid-color canvas and encode it.

    `has_alpha` + `center`: the product is located by the alpha bounding box
    (threshold ALPHA_BBOX_THRESHOLD), cropped, fitted inside the margin box
    and centered. Otherwise the WHOLE frame is fitted (original placement
    preserved). `offset_x/offset_y` (canvas px) and `scale` (multiplier on the
    fitted size) are the manual-repositioning knobs applied on top.
    """
    if ratio not in RATIOS:
        raise ValueError(f"unknown ratio {ratio!r}")
    if fmt not in _FORMATS:
        raise ValueError(f"unknown output format {fmt!r}")
    if not 0 <= margin_pct < 0.5:
        raise ValueError(f"margin_pct out of range: {margin_pct!r}")
    if scale <= 0:
        raise ValueError(f"scale must be positive: {scale!r}")

    normalized_fmt = _FORMATS[fmt][0]
    background = _parse_hex(bg_color)

    with Image.open(io.BytesIO(image)) as opened:
        src = opened.convert("RGBA")

    frame_w, frame_h = src.size
    if has_alpha and center:
        mask = src.getchannel("A").point(
            lambda v: 255 if v > ALPHA_BBOX_THRESHOLD else 0
        )
        bbox = mask.getbbox()
        if bbox is not None:
            src = src.crop(bbox)

    canvas_w, canvas_h = _canvas_size(ratio, frame_w, frame_h)
    canvas = Image.new("RGB", (canvas_w, canvas_h), background)

    # Fit inside the margin box, then the user scale on top.
    avail_w = canvas_w * (1 - 2 * margin_pct)
    avail_h = canvas_h * (1 - 2 * margin_pct)
    fit = min(avail_w / src.width, avail_h / src.height) * scale
    product = src.resize(
        (max(1, round(src.width * fit)), max(1, round(src.height * fit))),
        Image.Resampling.LANCZOS,
    )
    x = (canvas_w - product.width) // 2 + offset_x
    y = (canvas_h - product.height) // 2 + offset_y
    canvas.paste(product, (x, y), product)

    return ComposedImage(
        data=_encode(canvas, fmt, quality, max_kb),
        width=canvas_w,
        height=canvas_h,
        format=normalized_fmt,
    )
