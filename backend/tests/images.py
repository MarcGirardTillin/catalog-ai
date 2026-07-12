"""In-memory test image builders (Pillow), shared by the imaging suites."""

import io

from PIL import Image


def source_jpeg(
    width: int = 800, height: int = 1000, color: tuple[int, int, int] = (120, 30, 30)
) -> bytes:
    """A plain solid JPEG standing in for a product source photo."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "JPEG")
    return buffer.getvalue()


def cutout_png(
    width: int = 800,
    height: int = 1000,
    box: tuple[int, int, int, int] = (200, 300, 600, 700),
    color: tuple[int, int, int, int] = (10, 20, 200, 255),
) -> bytes:
    """Transparent canvas with one opaque rectangle (the "product").

    Mimics what Photoroom /v1/segment returns: PNG RGBA where only the
    subject has alpha.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rect = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), color)
    img.paste(rect, (box[0], box[1]))
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()
