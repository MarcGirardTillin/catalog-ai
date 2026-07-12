"""Tests of image file naming: slug rules + image title template."""

import pytest

from app.api.schemas import Brand, Product, ProductVariant
from app.imaging.naming import (
    build_filename,
    render_image_filename,
    slugify_filename,
)

PRODUCT = Product(
    id=101,
    title="G-Short Double Navy",
    reference_code="G5FU-T081",
    brand=Brand(id=7, name="Gramicci"),
    variants=[ProductVariant(id=11, sku="TIL-001", color="Bleu Marine")],
)


def test_slugify_strips_accents_spaces_and_symbols() -> None:
    assert slugify_filename("Photo Été #1 (face)") == "photo-ete-1-face"
    assert slugify_filename("  --weird__ .name.. ") == "weird__-.name"
    assert slugify_filename("???") == ""


def test_build_filename_imposes_extension_and_falls_back() -> None:
    assert build_filename("Mon Nom", "webp", default_stem="d") == "mon-nom.webp"
    # A matching extension in the custom name is deduplicated.
    assert build_filename("photo.webp", "webp", default_stem="d") == "photo.webp"
    assert build_filename("photo.PNG", "webp", default_stem="d") == "photo.webp"
    # Empty/None/unsluggable names fall back to the default stem.
    assert build_filename(None, "webp", default_stem="normalize_1_0") == (
        "normalize_1_0.webp"
    )
    assert build_filename("???", "png", default_stem="d") == "d.png"


def test_render_image_filename_renders_and_slugs_tokens() -> None:
    stem = render_image_filename(PRODUCT, 2, "{reference} {color} {position} {brand}")
    # NB: brand is not in the title here, so it renders.
    assert stem == "g5fu-t081-bleu-marine-2-gramicci"


def test_render_image_filename_keeps_free_text_segments() -> None:
    # Le builder front autorise du texte libre entre les tokens : le moteur
    # le rend tel quel puis tout est slugifié.
    stem = render_image_filename(PRODUCT, 3, "{reference} Face avant {position}")
    assert stem == "g5fu-t081-face-avant-3"


def test_render_image_filename_empty_template_and_unknown_token() -> None:
    assert render_image_filename(PRODUCT, 1, "{color}") == "bleu-marine"
    empty = Product(id=1, title="", variants=[])
    assert render_image_filename(empty, 1, "{color}") == ""
    with pytest.raises(ValueError):
        render_image_filename(PRODUCT, 1, "{season}")  # not an image token
