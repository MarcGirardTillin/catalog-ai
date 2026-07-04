"""Tests for weight conversion and variant weight mapping."""

from typing import Any

import pytest

from app.api.schemas import ProductVariant
from app.enrich.weights import map_weights, to_kg


def test_to_kg_conversions() -> None:
    assert to_kg(1000, "g") == 1.0
    assert to_kg(2, "kg") == 2.0
    assert to_kg(1, "lb") == pytest.approx(0.4536, abs=1e-4)
    assert to_kg(16, "oz") == pytest.approx(0.4536, abs=1e-4)


def test_to_kg_unknown_unit_raises() -> None:
    with pytest.raises(ValueError, match="Unknown weight unit"):
        to_kg(1, "stone")


def test_map_weights_matches_sku_then_barcode() -> None:
    tillin = [
        ProductVariant(id=1, sku="ABC-M", barcode="111"),
        ProductVariant(id=2, sku="TIL-XYZ", barcode="222"),  # sku won't match
        ProductVariant(id=3, sku=None, barcode="333"),
        ProductVariant(id=4, sku=None, barcode=None),  # unmatchable
    ]
    source: list[dict[str, Any]] = [
        {
            "sku": "abc-m",
            "barcode": "999",
            "grams": 300,
        },  # sku match (case-insensitive)
        {"sku": "OTHER", "barcode": "222", "grams": 450},  # barcode match
        {"sku": None, "barcode": "333", "weight": 1.2, "weight_unit": "lb"},
        {"sku": "ghost", "barcode": "000", "grams": 100},  # matches nothing
    ]

    proposals = map_weights(tillin, source)

    assert proposals == [
        {"variant_id": 1, "weight": 0.3, "weight_unit": "kg"},
        {"variant_id": 2, "weight": 0.45, "weight_unit": "kg"},
        {"variant_id": 3, "weight": 0.5443, "weight_unit": "kg"},
    ]


def test_map_weights_skips_zero_or_missing_weight() -> None:
    tillin = [ProductVariant(id=1, sku="A")]
    assert map_weights(tillin, [{"sku": "A", "grams": 0}]) == []
    assert map_weights(tillin, [{"sku": "A"}]) == []
    assert map_weights(tillin, [{"sku": "A", "weight": 1, "weight_unit": "wat"}]) == []
