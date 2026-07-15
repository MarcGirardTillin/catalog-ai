"""Tests for the by-color product split (profile option, applied at staging)."""

from app.imports.schema import ImportedProduct, ImportedVariant
from app.imports.split import split_products_by_color


def _variant(color: str | None, size: str = "M") -> ImportedVariant:
    return ImportedVariant(color=color, size=size, quantity=1)


def test_multi_color_product_splits_one_sheet_per_color() -> None:
    product = ImportedProduct(
        supplier_ref="B426AAC007810A",
        title="Tailored Jacket",
        variants=[
            _variant("BLACK", "S"),
            _variant("DARK OLIVE", "S"),
            _variant("BLACK", "M"),
        ],
    )
    out = split_products_by_color([product])
    assert [p.supplier_ref for p in out] == [
        "B426AAC007810A-BLACK",
        "B426AAC007810A-DARK-OLIVE",
    ]
    assert [[v.size for v in p.variants] for p in out] == [["S", "M"], ["S"]]
    # Shared fields are carried over on every sheet.
    assert all(p.title == "Tailored Jacket" for p in out)


def test_single_color_and_colorless_products_pass_through() -> None:
    single = ImportedProduct(supplier_ref="R1", variants=[_variant("Vert")])
    colorless = ImportedProduct(supplier_ref="R2", variants=[_variant(None)])
    out = split_products_by_color([single, colorless])
    assert [p.supplier_ref for p in out] == ["R1", "R2"]
    assert out[0] is single and out[1] is colorless


def test_colorless_variants_keep_the_unsuffixed_reference() -> None:
    product = ImportedProduct(
        supplier_ref="R3",
        variants=[_variant("Bleu"), _variant(None), _variant("Rouge")],
    )
    out = split_products_by_color([product])
    assert [p.supplier_ref for p in out] == ["R3-BLEU", "R3", "R3-ROUGE"]
    assert [len(p.variants) for p in out] == [1, 1, 1]
