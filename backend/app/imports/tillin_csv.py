"""Tillin import CSV rendering: staged products + profile -> CSV rows.

Single source of truth for the Tillin import template (column order matches
the real files under `everyday-tasks/*/imports tillin/*.csv`). The same
rows feed the JSON preview, the CSV download and the /product_import
transfer — never three implementations.
"""

import csv
import io
from decimal import ROUND_CEILING, Decimal
from typing import Any

from app.api.schemas.import_profiles import ImportProfileConfig
from app.imports.schema import ImportedProduct, ImportedVariant

# Exact template header, frozen against the real import files.
TILLIN_CSV_COLUMNS = [
    "id",
    "title",
    "description",
    "reference_code",
    "tags",
    "option1_name",
    "option1_value",
    "option2_name",
    "option2_value",
    "option3_name",
    "option3_value",
    "variant_barcode",
    "variant_sku",
    "weight",
    "weight_unit",
    "image_url",
    "wholesale_price",
    "wholesale_discount",
    "price",
    "tax_rate",
    "gender",
    "supplier",
    "brand",
    "category",
    "season",
    "composition",
    "harmonized_system_code",
    "manufacturing_country",
    "status",
    "quantity",
]


def format_decimal(value: Decimal) -> str:
    """Plain decimal string, trailing zeros stripped ("39.90" -> "39.9")."""
    normalized = value.normalize()
    # normalize() can produce exponent notation for round numbers (1E+3).
    # (exponent is typed int | Literal["n","N","F"]; finite values are ints.)
    exponent = normalized.as_tuple().exponent
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    return str(normalized)


def compute_price(
    variant: ImportedVariant, config: ImportProfileConfig
) -> Decimal | None:
    """CSV `price` for one variant, or None when the rule can't apply."""
    if config.price_mode == "retail_as_is":
        return variant.retail_price
    if config.coefficient is None or variant.wholesale_price is None:
        return None
    raw = variant.wholesale_price * config.coefficient
    step = config.round_up_to
    if step and step > 0:
        raw = (raw / step).to_integral_value(rounding=ROUND_CEILING) * step
    return raw


def compute_barcode(
    product: ImportedProduct, variant: ImportedVariant, config: ImportProfileConfig
) -> str:
    """CSV `variant_barcode`: extracted EAN, or constructed REF-COLOR-SIZE."""
    if config.barcode_mode == "ean":
        return variant.ean or ""
    parts = [product.supplier_ref, variant.color or "", variant.size or ""]
    return "-".join(part.strip() for part in parts if part.strip())


def render_rows(
    products: list[ImportedProduct],
    config: ImportProfileConfig,
    *,
    fallback_supplier: str | None = None,
) -> tuple[list[list[str]], list[str]]:
    """One CSV row per variant, in TILLIN_CSV_COLUMNS order, plus warnings.

    A product without variants yields no row (warned). Values already
    reviewed/edited in the grid arrive through `products` — this function
    only applies the profile conventions on top.
    """
    rows: list[list[str]] = []
    warnings: list[str] = []
    if config.price_mode == "coefficient" and config.coefficient is None:
        raise ValueError("price_mode 'coefficient' requires a coefficient")

    for product in products:
        if not product.variants:
            warnings.append(f"Réf {product.supplier_ref} : aucune variante — ignorée")
            continue
        title = product.title or product.supplier_ref
        brand = (
            config.brand_value if config.brand_mode == "fixed" else product.brand or ""
        )
        supplier = config.supplier_label or fallback_supplier or ""
        season = config.season_label or product.season or ""
        gender = product.gender or config.gender_default
        category = product.category or config.category_default
        image_url = product.image_urls[0] if product.image_urls else ""

        for variant in product.variants:
            price = compute_price(variant, config)
            if price is None:
                warnings.append(
                    f"Réf {product.supplier_ref}"
                    f"{f' {variant.color}/{variant.size}' if variant.color or variant.size else ''} :"
                    " prix de vente non calculable — colonne price vide"
                )
            barcode = compute_barcode(product, variant, config)
            if not barcode:
                warnings.append(
                    f"Réf {product.supplier_ref} : variante sans code-barres"
                )
            rows.append(
                _row(
                    {
                        "title": title,
                        "reference_code": product.supplier_ref,
                        "option1_name": "Couleur" if variant.color else "",
                        "option1_value": variant.color or "",
                        "option2_name": "Taille" if variant.size else "",
                        "option2_value": variant.size or "",
                        "variant_barcode": barcode,
                        "image_url": image_url,
                        "wholesale_price": (
                            format_decimal(variant.wholesale_price)
                            if variant.wholesale_price is not None
                            else ""
                        ),
                        "wholesale_discount": "0",
                        "price": format_decimal(price) if price is not None else "",
                        "tax_rate": config.tax_rate,
                        "gender": gender,
                        "supplier": supplier,
                        "brand": brand,
                        "category": category,
                        "season": season,
                        "composition": product.composition or "",
                        "harmonized_system_code": product.hs_code or "",
                        "manufacturing_country": product.manufacturing_country or "",
                        "status": config.status,
                        "quantity": str(
                            variant.quantity if variant.quantity is not None else 1
                        ),
                    }
                )
            )
    return rows, warnings


def _row(values: dict[str, str]) -> list[str]:
    return [values.get(column, "") for column in TILLIN_CSV_COLUMNS]


def render_csv(rows: list[list[str]]) -> str:
    """Header + rows as CSV text (comma-separated, like the real template)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TILLIN_CSV_COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue()


def products_from_payloads(payloads: list[dict[str, Any]]) -> list[ImportedProduct]:
    """Validate stored `payload_json` dicts back into ImportedProduct."""
    return [ImportedProduct.model_validate(payload) for payload in payloads]
