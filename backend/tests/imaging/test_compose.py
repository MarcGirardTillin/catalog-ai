"""Unit tests of the local Pillow composition engine (pure, no IO)."""

import io
import os

import pytest
from PIL import Image

from app.imaging.compose import CANVAS_LONG_SIDE, compose, probe
from tests.images import cutout_png, source_jpeg

PRODUCT = (10, 20, 200)  # the opaque rectangle color of cutout_png
BACKGROUND = (245, 245, 245)


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _compose_png(**overrides: object) -> Image.Image:
    """Compose the default cutout to PNG (lossless → exact pixel asserts)."""
    kwargs: dict[str, object] = {
        "has_alpha": True,
        "bg_color": "F5F5F5",
        "fmt": "png",
    }
    kwargs.update(overrides)
    result = compose(cutout_png(), **kwargs)  # type: ignore[arg-type]
    return _open(result.data)


def test_probe_reads_dimensions_and_format() -> None:
    assert probe(source_jpeg(640, 480)) == (640, 480, "jpeg")
    assert probe(cutout_png())[2] == "png"


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        ("4:5", (1600, 2000)),
        ("1:1", (2000, 2000)),
        ("3:4", (1500, 2000)),
        ("16:9", (2000, 1125)),
    ],
)
def test_canvas_follows_the_requested_ratio(
    ratio: str, expected: tuple[int, int]
) -> None:
    result = compose(cutout_png(), has_alpha=True, ratio=ratio, fmt="png")
    assert (result.width, result.height) == expected


def test_ratio_original_keeps_the_frame_ratio_and_caps_the_long_side() -> None:
    # 800x1000 frame: under the cap, kept as-is.
    small = compose(cutout_png(800, 1000), has_alpha=True, ratio="original", fmt="png")
    assert (small.width, small.height) == (800, 1000)
    # 3000x4000 frame: downscaled to the 2000px long side, ratio preserved.
    big = compose(
        cutout_png(3000, 4000, box=(500, 500, 2500, 3500)),
        has_alpha=True,
        ratio="original",
        fmt="png",
    )
    assert (big.width, big.height) == (1500, CANVAS_LONG_SIDE)


def test_product_is_cropped_to_its_alpha_bbox_and_centered() -> None:
    # The rectangle sits off-center in the source; centering must relocate it.
    img = _compose_png()
    cx, cy = img.width // 2, img.height // 2
    assert img.getpixel((cx, cy)) == PRODUCT
    assert img.getpixel((5, 5)) == BACKGROUND
    # The margin box is honoured: 10% borders stay background.
    assert img.getpixel((int(img.width * 0.05), cy)) == BACKGROUND


def test_offsets_shift_the_product_on_the_canvas() -> None:
    base = _compose_png()
    shifted = _compose_png(offset_x=300, offset_y=0)
    cx, cy = base.width // 2, base.height // 2
    # Product region moved right: far-left of the old spot is now background.
    assert base.getpixel((cx - 400, cy)) == PRODUCT
    assert shifted.getpixel((cx - 400, cy)) == BACKGROUND
    assert shifted.getpixel((cx + 300, cy)) == PRODUCT


def test_scale_shrinks_or_grows_the_product() -> None:
    def product_pixels(img: Image.Image) -> int:
        return sum(1 for pixel in img.getdata() if pixel == PRODUCT)

    full = product_pixels(_compose_png())
    half = product_pixels(_compose_png(scale=0.5))
    assert 0 < half < full * 0.35  # ~25% expected, tolerance for rounding


def test_without_alpha_the_whole_frame_is_fitted() -> None:
    result = compose(
        source_jpeg(800, 1000), has_alpha=False, bg_color="F5F5F5", fmt="png"
    )
    img = _open(result.data)
    # The frame (solid red-ish) is letterboxed inside the margin box.
    assert img.getpixel((img.width // 2, img.height // 2)) == (120, 30, 30)
    assert img.getpixel((5, 5)) == BACKGROUND


def test_max_kb_loops_the_quality_down() -> None:
    # Random noise compresses poorly: the loop must kick in.
    noise = Image.frombytes("RGB", (600, 750), os.urandom(600 * 750 * 3))
    buffer = io.BytesIO()
    noise.save(buffer, "PNG")
    data = buffer.getvalue()

    unbounded = compose(data, has_alpha=False, fmt="jpeg", quality=95, max_kb=None)
    bounded = compose(data, has_alpha=False, fmt="jpeg", quality=95, max_kb=40)
    assert len(bounded.data) < len(unbounded.data)


def test_bg_color_accepts_leading_hash_and_rejects_garbage() -> None:
    img = _compose_png(bg_color="#102030")
    assert img.getpixel((5, 5)) == (0x10, 0x20, 0x30)
    with pytest.raises(ValueError):
        compose(cutout_png(), has_alpha=True, bg_color="not-a-color")
    with pytest.raises(ValueError):
        compose(cutout_png(), has_alpha=True, ratio="2:3")
    with pytest.raises(ValueError):
        compose(cutout_png(), has_alpha=True, fmt="gif")


def test_jpg_alias_normalizes_to_jpeg() -> None:
    result = compose(cutout_png(), has_alpha=True, fmt="jpg")
    assert result.format == "jpeg"
    assert probe(result.data)[2] == "jpeg"
