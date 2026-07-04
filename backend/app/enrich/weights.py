"""Variant weight mapping: source-site variants -> Tillin variants.

Matching is by SKU first, then barcode (plan). Weights are normalized to kg
(`to_kg` ported from the Xano `1079` function's toKg).
"""

from typing import Any

from app.api.schemas import ProductVariant

_TO_KG = {
    "kg": 1.0,
    "g": 0.001,
    "lb": 0.45359237,
    "oz": 0.028349523125,
}


def to_kg(value: float, unit: str) -> float:
    """Convert a weight to kilograms; unknown units raise."""
    factor = _TO_KG.get(unit.strip().lower())
    if factor is None:
        raise ValueError(f"Unknown weight unit: {unit!r}")
    return value * factor


def map_weights(
    tillin_variants: list[ProductVariant],
    source_variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Propose `{variant_id, weight, weight_unit}` rows for matched variants.

    Source variants are Shopify-style dicts: `sku`, `barcode`, `grams` or
    `weight`+`weight_unit`. Unmatched Tillin variants are skipped (never
    guessed).
    """
    by_sku: dict[str, dict[str, Any]] = {}
    by_barcode: dict[str, dict[str, Any]] = {}
    for source in source_variants:
        if source.get("sku"):
            by_sku.setdefault(str(source["sku"]).strip().lower(), source)
        if source.get("barcode"):
            by_barcode.setdefault(str(source["barcode"]).strip(), source)

    proposals: list[dict[str, Any]] = []
    for variant in tillin_variants:
        match: dict[str, Any] | None = None
        if variant.sku:
            match = by_sku.get(variant.sku.strip().lower())
        if match is None and variant.barcode:
            match = by_barcode.get(variant.barcode.strip())
        if match is None or variant.id is None:
            continue

        weight_kg = _extract_weight_kg(match)
        if weight_kg is None or weight_kg <= 0:
            continue
        proposals.append(
            {
                "variant_id": variant.id,
                "weight": round(weight_kg, 4),
                "weight_unit": "kg",
            }
        )
    return proposals


def _extract_weight_kg(source: dict[str, Any]) -> float | None:
    grams = source.get("grams")
    if isinstance(grams, int | float) and grams:
        return float(grams) / 1000.0
    weight = source.get("weight")
    unit = source.get("weight_unit")
    if isinstance(weight, int | float) and isinstance(unit, str):
        try:
            return to_kg(float(weight), unit)
        except ValueError:
            return None
    return None
