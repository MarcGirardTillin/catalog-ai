"""Tests for the Tillin import CSV engine (frozen I2 contract).

The expected values mirror the REAL import files under everyday-tasks:
- L'Espion (template_import_barbarabui_*.csv): PA 440, coefficient 2.8
  -> 1232 rounded UP to the nearest 5 = 1235; barcode J1103GAH-48-T1.
- Bambinoh (import_garcia_*.csv): price = retail as printed (49.99),
  real EANs, season H26.
"""

from decimal import Decimal

import pytest

from app.api.schemas.import_profiles import ImportProfileConfig, OptionAxis
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


def test_warns_when_extra_values_lost_without_third_axis() -> None:
    # Profil à 2 axes (défaut) + valeurs d'option 3 extraites : perte
    # silencieuse interdite — un avertissement nomme les valeurs perdues.
    config = ImportProfileConfig()
    product = ImportedProduct(
        supplier_ref="PA-SEMB-DENIMB",
        variants=[
            ImportedVariant(color="Denim bleu", size="31", extra="STANDARD", ean="1"),
            ImportedVariant(color="Denim bleu", size="31", extra="LONG", ean="2"),
        ],
    )

    rows, warnings = render_rows([product], config)

    assert len(rows) == 2
    assert any(
        "PA-SEMB-DENIMB" in w and "option 3" in w and "LONG" in w and "STANDARD" in w
        for w in warnings
    )


def test_no_extra_warning_when_profile_has_third_axis() -> None:
    config = ImportProfileConfig(
        option_axes=[
            OptionAxis(source="color", label="Couleur"),
            OptionAxis(source="size", label="Taille"),
            OptionAxis(source="extra", label="Coupe"),
        ]
    )
    product = ImportedProduct(
        supplier_ref="PA-SEMB-DENIMB",
        variants=[
            ImportedVariant(color="Denim bleu", size="31", extra="LONG", ean="1")
        ],
    )

    rows, warnings = render_rows([product], config)

    assert _col(rows[0], "option3_name") == "Coupe"
    assert _col(rows[0], "option3_value") == "LONG"
    assert not any("option 3" in w for w in warnings)


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


def test_pipes_are_replaced_in_rendered_values() -> None:
    """Décision Marc 2026-07-18 : « | » → « / » au rendu Tillin (titres
    fournisseurs type « 399 | Ilyano », vécu Garcia) — y compris dans le
    code-barres construit."""
    product = ImportedProduct(
        supplier_ref="399|A",
        title="399 | Ilyano Straight F",
        brand="Garcia",
        variants=[
            ImportedVariant(color="Medium|Used", size="176", quantity=1),
        ],
    )
    config = ImportProfileConfig(price_mode="retail_as_is", barcode_mode="constructed")
    rows, _warnings = render_rows([product], config)

    row = rows[0]
    assert _col(row, "title") == "399 / Ilyano Straight F"
    assert _col(row, "reference_code") == "399 / A"
    assert _col(row, "option1_value") == "Medium / Used"
    assert _col(row, "variant_barcode") == "399 / A-Medium / Used-176"


def test_option_names_follow_profile() -> None:
    """Noms d'options configurables par profil (ex. Pointure)."""
    product = ImportedProduct(
        supplier_ref="SHOE-1",
        title="Bottine",
        variants=[ImportedVariant(color="Noir", size="38", quantity=1)],
    )
    config = ImportProfileConfig(
        price_mode="retail_as_is",
        option_axes=[
            OptionAxis(source="color", label="Couleur"),
            OptionAxis(source="size", label="Pointure"),
        ],
    )
    rows, _ = render_rows([product], config)
    assert _col(rows[0], "option1_name") == "Couleur"
    assert _col(rows[0], "option2_name") == "Pointure"


def test_size_conversion_uk_to_eu_at_render() -> None:
    """Pointures UK converties en EU au rendu (option + code-barres),
    payload extrait intact ; tailles non numériques inchangées."""
    product = ImportedProduct(
        supplier_ref="SHOE-2",
        title="Derby",
        gender="Homme",
        variants=[
            ImportedVariant(color="Noir", size="UK 8", quantity=1),
            ImportedVariant(color="Noir", size="8.5", quantity=1),
            ImportedVariant(color="Noir", size="M", quantity=1),
        ],
    )
    config = ImportProfileConfig(
        price_mode="retail_as_is",
        barcode_mode="constructed",
        size_conversion="uk_to_eu",
    )
    rows, _ = render_rows([product], config)
    assert _col(rows[0], "option2_value") == "42"  # UK 8 homme -> 42
    assert _col(rows[0], "variant_barcode") == "SHOE-2-Noir-42"
    assert _col(rows[1], "option2_value") == "42.5"
    assert _col(rows[2], "option2_value") == "M"  # non numérique : intact
    # La donnée d'origine n'a pas bougé.
    assert product.variants[0].size == "UK 8"


def test_size_conversion_women_grid() -> None:
    from app.imports.tillin_csv import convert_shoe_size

    assert convert_shoe_size("6", "uk_to_eu", "Femme") == "39"
    assert convert_shoe_size("8", "us_to_eu", "Femme") == "39"
    assert convert_shoe_size("9", "us_to_eu", "Homme") == "42"
    assert convert_shoe_size("176", "uk_to_eu", "Homme") == "176"  # hors plage


def test_category_default_weight_fills_weight_columns() -> None:
    """Poids par défaut par catégorie (default_weight_kg Xano) : rempli au
    rendu quand la catégorie en définit un, sinon colonnes vides."""
    product = ImportedProduct(
        supplier_ref="ACC-1",
        title="Ceinture",
        category="Accessoire",
        variants=[ImportedVariant(color="Noir", size="U", quantity=1)],
    )
    config = ImportProfileConfig(price_mode="retail_as_is")
    rows, _ = render_rows([product], config, category_weights={"accessoire": 0.25})
    assert _col(rows[0], "weight") == "0.25"
    assert _col(rows[0], "weight_unit") == "kg"

    rows_no, _ = render_rows([product], config)
    assert _col(rows_no[0], "weight") == ""
    assert _col(rows_no[0], "weight_unit") == ""


def test_option_axes_reordered_render_size_first() -> None:
    config = ImportProfileConfig(
        price_mode="retail_as_is",
        option_axes=[
            OptionAxis(source="size", label="Taille"),
            OptionAxis(source="color", label="Couleur"),
        ],
    )
    product = ImportedProduct(
        supplier_ref="REF-1",
        variants=[ImportedVariant(color="Marine", size="M", retail_price=Decimal(10))],
    )

    rows, _ = render_rows([product], config)

    assert _col(rows[0], "option1_name") == "Taille"
    assert _col(rows[0], "option1_value") == "M"
    assert _col(rows[0], "option2_name") == "Couleur"
    assert _col(rows[0], "option2_value") == "Marine"
    assert _col(rows[0], "option3_name") == ""


def test_option_axes_third_extra_axis_and_constructed_barcode() -> None:
    config = ImportProfileConfig(
        price_mode="retail_as_is",
        barcode_mode="constructed",
        option_axes=[
            OptionAxis(source="color", label="Couleur"),
            OptionAxis(source="size", label="Tour de dos"),
            OptionAxis(source="extra", label="Bonnet"),
        ],
    )
    product = ImportedProduct(
        supplier_ref="SG100",
        variants=[
            ImportedVariant(
                color="Noir", size="90", extra="C", retail_price=Decimal(45)
            ),
            # Variante sans 3e dimension : libellé option3 vide, barcode sans
            # segment supplémentaire.
            ImportedVariant(color="Noir", size="95", retail_price=Decimal(45)),
        ],
    )

    rows, _ = render_rows([product], config)

    assert _col(rows[0], "option2_name") == "Tour de dos"
    assert _col(rows[0], "option3_name") == "Bonnet"
    assert _col(rows[0], "option3_value") == "C"
    # Le code construit reste canonique (réf-couleur-taille-extra), quel que
    # soit l'ordre d'affichage des axes.
    assert _col(rows[0], "variant_barcode") == "SG100-Noir-90-C"
    assert _col(rows[1], "option3_name") == ""
    assert _col(rows[1], "variant_barcode") == "SG100-Noir-95"


def test_option_axes_legacy_config_keys_converted() -> None:
    # Configs stockées avant option_axes : les libellés historiques sont
    # convertis en deux axes couleur/taille dans l'ordre d'origine.
    config = ImportProfileConfig.model_validate(
        {"price_mode": "retail_as_is", "size_option_name": "Pointure"}
    )

    assert [(a.source, a.label) for a in config.option_axes] == [
        ("color", "Couleur"),
        ("size", "Pointure"),
    ]


def test_option_axes_duplicate_sources_rejected() -> None:
    with pytest.raises(ValueError):
        ImportProfileConfig(
            option_axes=[
                OptionAxis(source="color", label="Couleur"),
                OptionAxis(source="color", label="Coloris"),
            ]
        )
