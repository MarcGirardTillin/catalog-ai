"""Tests for title templating."""

import pytest

from app.api.schemas import Brand, Product
from app.enrich.title import apply_title_template

PRODUCT = Product(
    id=1,
    title="G-Short Double Navy",
    reference_code="G5FU-T081",
    brand=Brand(name="Gramicci"),
    season="SS25",
    category="Shorts",
    department="Men",
)


def test_renders_all_tokens() -> None:
    result = apply_title_template(PRODUCT, "{brand} {title} {season} ({reference})")
    assert result == "Gramicci G-Short Double Navy SS25 (G5FU-T081)"


def test_missing_values_collapse_whitespace() -> None:
    bare = Product(id=2, title="Chose")
    assert apply_title_template(bare, "{brand} {title} {season}") == "Chose"


def test_color_token_is_accepted_but_empty_for_now() -> None:
    assert apply_title_template(PRODUCT, "{title} {color}") == "G-Short Double Navy"


def test_unknown_token_raises() -> None:
    with pytest.raises(ValueError, match="Unknown title template token"):
        apply_title_template(PRODUCT, "{brand} {nope}")


def _product(title: str, brand: str | None) -> Product:
    return Product(id=3, title=title, brand=Brand(name=brand) if brand else None)


def test_brand_already_leading_title_is_not_duplicated() -> None:
    product = _product(
        "ARMEDANGELS Polo rayé en coton bio · écru et vert clair - Vert",
        "ARMEDANGELS",
    )
    assert (
        apply_title_template(product, "{brand} {title}")
        == "ARMEDANGELS Polo rayé en coton bio · écru et vert clair - Vert"
    )


def test_brand_in_middle_of_title_is_not_duplicated() -> None:
    product = _product("Polo Gramicci en coton", "Gramicci")
    assert apply_title_template(product, "{brand} {title}") == "Polo Gramicci en coton"


def test_brand_absent_from_title_is_prepended() -> None:
    assert (
        apply_title_template(PRODUCT, "{brand} {title}")
        == "Gramicci G-Short Double Navy"
    )


def test_brand_match_is_case_insensitive() -> None:
    product = _product("armedangels Polo rayé", "ARMEDANGELS")
    assert apply_title_template(product, "{brand} {title}") == "armedangels Polo rayé"


def test_brand_substring_of_word_does_not_count() -> None:
    # "Gram" is only part of "Gramicci" — the brand is still prepended.
    product = _product("Gramicci Short", "Gram")
    assert apply_title_template(product, "{brand} {title}") == "Gram Gramicci Short"


def test_case_none_leaves_title_untouched() -> None:
    assert (
        apply_title_template(PRODUCT, "{brand} {title}", "none")
        == "Gramicci G-Short Double Navy"
    )


def test_case_upper() -> None:
    assert (
        apply_title_template(PRODUCT, "{brand} {title}", "upper")
        == "GRAMICCI G-SHORT DOUBLE NAVY"
    )


def test_case_capitalize_first_letter_of_each_word_preserving_rest() -> None:
    product = _product("polo rayé en COTON bio", "armedangels")
    # First letter of each word upper-cased; existing caps (COTON) preserved.
    assert (
        apply_title_template(product, "{title}", "capitalize")
        == "Polo Rayé En COTON Bio"
    )
