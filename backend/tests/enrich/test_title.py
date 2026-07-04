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
