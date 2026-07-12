"""Image file naming: slugification + the image title template.

The template reuses the product-title engine (`app.enrich.title`) with an
image-specific token set (adds `{position}`); the rendered name is always
slugged, so casing is irrelevant here (filenames are lowercase by design).
"""

import re
import unicodedata

from app.api.schemas import Product
from app.enrich.title import _token_values, render_title_template

# Tokens offered by the image title template builder.
IMAGE_TOKENS = ("reference", "color", "position", "brand", "title")

# Extensions we strip from user-provided names before re-appending the real
# output extension (avoids "photo.webp.webp").
_KNOWN_EXTENSIONS = ("webp", "jpeg", "jpg", "png")


def slugify_filename(name: str) -> str:
    """ASCII-safe, lowercase, dash-separated file stem ("" when nothing survives)."""
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return value.strip("-._").lower()


def render_image_filename(product: Product, position: int, template: str) -> str:
    """Rendered file STEM from the image title template ("" when it renders
    empty — callers fall back to the default technical name).

    `_token_values` is the product-title token map (same package family);
    only the image tokens are kept, plus the position.
    """
    values = {
        key: value
        for key, value in _token_values(product).items()
        if key in IMAGE_TOKENS
    }
    values["position"] = str(position)
    return slugify_filename(render_title_template(values, template))


def build_filename(name: str | None, extension: str, *, default_stem: str) -> str:
    """Final upload filename: slugged custom name or the default stem.

    The output extension is imposed (it reflects the encoded format); a
    matching extension already present in `name` is stripped first.
    """
    stem = slugify_filename(name or "")
    for known in _KNOWN_EXTENSIONS:
        if stem.endswith(f".{known}"):
            stem = stem[: -(len(known) + 1)].rstrip("-._")
            break
    if not stem:
        stem = default_stem
    return f"{stem}.{extension}"
