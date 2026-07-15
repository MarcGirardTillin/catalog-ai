"""Split multi-color extracted products into one product per color.

The extractor reconciles document lines by supplier reference, which merges
colorways into variants of a single product (the Tillin default model). Some
boutiques want ONE SHEET PER COLOR instead (`ImportProfileConfig.
split_by_color`): this module re-expands those products at staging time, so
downstream (review grid, credits, CSV, transfer) simply sees more products.

The reference is suffixed with the color so Tillin's `reference_code` stays
unique across the split sheets; variants without a color keep the original
reference, unsuffixed.
"""

import re

from app.imports.schema import ImportedProduct


def _color_suffix(color: str) -> str:
    """ "Dark Olive" -> "DARK-OLIVE" (reference-safe, uppercased)."""
    return re.sub(r"[^A-Za-z0-9]+", "-", color.strip()).strip("-").upper()


def split_products_by_color(
    products: list[ImportedProduct],
) -> list[ImportedProduct]:
    """One product per distinct variant color; single-color products pass through.

    Variant order is preserved inside each group, and groups come out in the
    order their color first appears in the document.
    """
    out: list[ImportedProduct] = []
    for product in products:
        colors: list[str] = []
        for variant in product.variants:
            color = (variant.color or "").strip()
            if color not in colors:
                colors.append(color)
        real_colors = [color for color in colors if color]
        if len(real_colors) <= 1:
            out.append(product)
            continue
        for color in colors:
            variants = [v for v in product.variants if (v.color or "").strip() == color]
            suffix = _color_suffix(color)
            out.append(
                product.model_copy(
                    update={
                        "supplier_ref": (
                            f"{product.supplier_ref}-{suffix}"
                            if suffix
                            else product.supplier_ref
                        ),
                        "variants": variants,
                    }
                )
            )
    return out
