"""Tests for the Tillin import CSV engine (frozen I2 contract).

The expected values mirror the REAL import files under everyday-tasks:
- L'Espion (template_import_barbarabui_*.csv): PA 440, coefficient 2.8
  -> 1232 rounded UP to the nearest 5 = 1235; barcode J1103GAH-48-T1.
- Bambinoh (import_garcia_*.csv): price = retail as printed (49.99),
  real EANs, season H26.
"""

from decimal import Decimal

import pytest

from app.api.schemas.import_profiles import ImportProfileConfig
from app.imports.schema import ImportedProduct, ImportedVariant
from app.imports.tillin_csv import (
    TILLIN_CSV_COLUMNS,
    compute_price,
    format_decimal,
    render_csv,
    render_rows,
)


def _col(row: list[str], name: str) -> str:
    return row[TILLIN_CSV_COLUMNS.index(name)]


def _lespion_config() -> ImportProfileConfig:
    return ImportProfileConfig(
        price_mode="coefficient",
        coefficient=Decimal("2.8"),
        round_up_to=Decimal(5),
        barcode_mode="constructed",
        supplier_label="L'ESPION",
        season_label="HIVER 2026",
    )


def _barbara_bui() -> ImportedProduct:
    return ImportedProduct(
        supplier_ref="J1103GAH",
        title="Manteau",
        brand="BARBARA BUI",
        # Gender is a per-product fact (edited in the review grid), no longer
        # a profile default.
        gender="Femme",
        composition="90% Laine 10% Cachemire",
        variants=[
            ImportedVariant(
                color="48", size="T1", quantity=1, wholesale_price=Decimal(440)
            ),
            ImportedVariant(
                color="48", size="T2", quantity=1, wholesale_price=Decimal(440)
            ),
        ],
    )


def test_lespion_row_matches_real_import_file() -> None:
    rows, warnings = render_rows([_barbara_bui()], _lespion_config())

    assert warnings == []
    assert len(rows) == 2
    row = rows[0]
    assert _col(row, "title") == "Manteau"
    assert _col(row, "reference_code") == "J1103GAH"
    assert _col(row, "option1_name") == "Couleur"
    assert _col(row, "option1_value") == "48"
    assert _col(row, "option2_name") == "Taille"
    assert _col(row, "option2_value") == "T1"
    # Constructed barcode (PDF orders carry no EAN).
    assert _col(row, "variant_barcode") == "J1103GAH-48-T1"
    assert _col(row, "wholesale_price") == "440"
    assert _col(row, "wholesale_discount") == "0"
    # 440 x 2.8 = 1232 -> rounded UP to the nearest 5.
    assert _col(row, "price") == "1235"
    assert _col(row, "tax_rate") == "20"
    assert _col(row, "wholesale_tax_rate") == "20"  # purchase-price tax
    assert _col(row, "gender") == "Femme"
    assert _col(row, "supplier") == "L'ESPION"
    assert _col(row, "brand") == "BARBARA BUI"
    assert _col(row, "season") == "HIVER 2026"
    assert _col(row, "composition") == "90% Laine 10% Cachemire"
    assert _col(row, "status") == "active"
    assert _col(row, "quantity") == "1"
    assert rows[1][TILLIN_CSV_COLUMNS.index("variant_barcode")] == "J1103GAH-48-T2"


def test_bambinoh_row_uses_retail_price_and_real_ean() -> None:
    config = ImportProfileConfig(
        price_mode="retail_as_is",
        barcode_mode="ean",
        brand_mode="fixed",
        brand_value="garcia",
        supplier_label="Garcia",
        season_label="H26",
    )
    product = ImportedProduct(
        supplier_ref="S262651",
        category="Junior",
        variants=[
            ImportedVariant(
                ean="8717519401304",
                color="Soft Grey Melee",
                size="128/134",
                quantity=1,
                wholesale_price=Decimal("19.94"),
                retail_price=Decimal("49.99"),
            )
        ],
    )

    rows, warnings = render_rows([product], config)

    assert warnings == []
    row = rows[0]
    # No extracted title: the reference is the title (as in the real files).
    assert _col(row, "title") == "S262651"
    assert _col(row, "variant_barcode") == "8717519401304"
    assert _col(row, "wholesale_price") == "19.94"
    assert _col(row, "price") == "49.99"
    assert _col(row, "brand") == "garcia"
    assert _col(row, "supplier") == "Garcia"
    assert _col(row, "category") == "Junior"
    assert _col(row, "season") == "H26"


def test_title_template_applied_at_import_when_flag_set() -> None:
    config = ImportProfileConfig(
        brand_mode="fixed",
        brand_value="SALOMON",
        season_label="FW26",
        apply_title_template=True,
    )
    product = ImportedProduct(
        supplier_ref="XT6",
        title="XT-6",
        variants=[ImportedVariant(color="Noir", size="42", ean="1")],
    )
    rows, _ = render_rows(
        [product],
        config,
        title_template="{brand} {title} {color} {season}",
        title_case="none",
    )
    assert _col(rows[0], "title") == "SALOMON XT-6 Noir FW26"


def test_title_template_ignored_when_flag_off() -> None:
    config = ImportProfileConfig(apply_title_template=False)
    product = ImportedProduct(
        supplier_ref="XT6",
        title="XT-6",
        variants=[ImportedVariant(color="Noir", ean="1")],
    )
    rows, _ = render_rows([product], config, title_template="{brand} {title} {color}")
    # Flag off: the raw extracted title is kept untouched.
    assert _col(rows[0], "title") == "XT-6"


def test_supplier_falls_back_to_document_supplier() -> None:
    config = ImportProfileConfig()
    product = ImportedProduct(
        supplier_ref="R1",
        variants=[ImportedVariant(ean="3607814866838")],
    )
    rows, _ = render_rows([product], config, fallback_supplier="L'Espion")
    assert _col(rows[0], "supplier") == "L'Espion"


def test_warnings_for_missing_price_barcode_and_variants() -> None:
    config = ImportProfileConfig(
        price_mode="coefficient", coefficient=Decimal(2), barcode_mode="ean"
    )
    products = [
        ImportedProduct(supplier_ref="SANS-VARIANTE"),
        ImportedProduct(
            supplier_ref="R1",
            variants=[ImportedVariant(color="Rouge", size="36")],  # no price, no EAN
        ),
    ]

    rows, warnings = render_rows(products, config)

    assert len(rows) == 1
    assert _col(rows[0], "price") == ""
    assert _col(rows[0], "variant_barcode") == ""
    assert _col(rows[0], "quantity") == "1"  # missing quantity = 1 unit
    assert any("SANS-VARIANTE" in w and "aucune variante" in w for w in warnings)
    assert any("prix de vente non calculable" in w for w in warnings)
    assert any("sans code-barres" in w for w in warnings)


def test_coefficient_mode_requires_coefficient() -> None:
    config = ImportProfileConfig(price_mode="coefficient")
    with pytest.raises(ValueError, match="coefficient"):
        render_rows([_barbara_bui()], config)


def test_compute_price_rounds_up_to_step() -> None:
    config = ImportProfileConfig(
        price_mode="coefficient", coefficient=Decimal("2.8"), round_up_to=Decimal(5)
    )
    variant = ImportedVariant(wholesale_price=Decimal(100))
    assert compute_price(variant, config) == Decimal(280)  # exact multiple stays
    variant = ImportedVariant(wholesale_price=Decimal(101))
    assert compute_price(variant, config) == Decimal(285)  # 282.8 -> up to 285


def test_format_decimal_strips_trailing_zeros() -> None:
    assert format_decimal(Decimal("39.90")) == "39.9"
    assert format_decimal(Decimal("440")) == "440"
    assert format_decimal(Decimal("1235")) == "1235"
    assert format_decimal(Decimal("49.99")) == "49.99"
    assert format_decimal(Decimal("1000")) == "1000"  # no 1E+3 notation


def test_render_csv_has_exact_template_header() -> None:
    rows, _ = render_rows([_barbara_bui()], _lespion_config())
    text = render_csv(rows)
    lines = text.splitlines()
    assert lines[0] == ",".join(TILLIN_CSV_COLUMNS)
    assert len(lines) == 3
    assert lines[1].startswith(",Manteau,,J1103GAH,")
