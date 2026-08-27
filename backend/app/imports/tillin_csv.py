"""Tillin import CSV rendering: staged products + profile -> CSV rows.

Single source of truth for the Tillin import template (column order matches
the real files under `everyday-tasks/*/imports tillin/*.csv`). The same
rows feed the JSON preview, the CSV download and the /product_import
transfer — never three implementations.
"""

import csv
import io
import re
from decimal import ROUND_CEILING, Decimal
from typing import Any

from app.api.schemas.import_profiles import ImportProfileConfig
from app.api.schemas.settings import TitleCase
from app.enrich.title import render_title_template
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
    "wholesale_tax_rate",
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


def depipe(value: str) -> str:
    """Remplace « | » par « / » (décision Marc 2026-07-18).

    Filet de sécurité au rendu : l'extraction nettoie déjà les nouveaux
    imports, mais les payloads existants (et les éditions manuelles) peuvent
    encore porter des pipes — traités comme séparateur par le gabarit de
    titre et gênants dans les identifiants dérivés.
    """
    if "|" not in value:
        return value
    return " / ".join(part.strip() for part in value.split("|") if part.strip())


def compute_barcode(
    product: ImportedProduct, variant: ImportedVariant, config: ImportProfileConfig
) -> str:
    """CSV `variant_barcode`: extracted EAN, or constructed REF-COLOR-SIZE.

    L'ordre du code construit est CANONIQUE (réf, couleur, taille, puis la
    3e dimension si le profil en rend une) : réordonner les options affichées
    ne change pas l'identifiant — il sert de lien stable post-transfert.
    """
    if config.barcode_mode == "ean":
        return variant.ean or ""
    parts = [product.supplier_ref, variant.color or "", variant.size or ""]
    if any(axis.source == "extra" for axis in config.option_axes):
        parts.append(variant.extra or "")
    return "-".join(depipe(part.strip()) for part in parts if part.strip())


# Décalages pointure → EU par grille standard adulte (approximation assumée,
# décision Marc 2026-07-18 : conversion visible dans l'aperçu avant transfert).
# Genre « Femme » vs autres (Homme/Unisexe → grille homme).
_SIZE_OFFSETS = {
    "uk_to_eu": {"femme": 33.0, "default": 34.0},
    "us_to_eu": {"femme": 31.0, "default": 33.0},
}


def convert_shoe_size(size: str | None, mode: str, gender: str | None) -> str | None:
    """Pointure UK/US → EU (rendu uniquement) ; inconvertible = inchangée.

    Accepte « 8 », « 8.5 », « UK 8 », « US9 »… — la partie numérique est
    convertie, le reste est ignoré. Une taille non numérique (S/M/L, 176…)
    reste telle quelle.
    """
    if not size or mode not in _SIZE_OFFSETS:
        return size
    match = re.search(r"\d+(?:[.,]5)?", size)
    if match is None:
        return size
    value = float(match.group(0).replace(",", "."))
    if not 1 <= value <= 16:  # hors plage pointure adulte : ne pas toucher
        return size
    offsets = _SIZE_OFFSETS[mode]
    offset = (
        offsets["femme"]
        if (gender or "").strip().lower() == "femme"
        else (offsets["default"])
    )
    converted = value + offset
    return f"{converted:g}"


def _product_color(product: ImportedProduct) -> str:
    """First non-empty variant color (boutique convention: one color/product)."""
    colors: list[str] = []
    for variant in product.variants:
        color = (variant.color or "").strip()
        if color and color not in colors:
            colors.append(color)
    return " / ".join(colors)


def render_rows(
    products: list[ImportedProduct],
    config: ImportProfileConfig,
    *,
    fallback_supplier: str | None = None,
    title_template: str | None = None,
    title_case: TitleCase = "none",
    category_weights: dict[str, float] | None = None,
) -> tuple[list[list[str]], list[str]]:
    """One CSV row per variant, in TILLIN_CSV_COLUMNS order, plus warnings.

    A product without variants yields no row (warned). Values already
    reviewed/edited in the grid arrive through `products` — this function
    only applies the profile conventions on top.

    When `config.apply_title_template` is set and a `title_template` is given
    (the account default, from settings), the CSV `title` is rendered from
    that template instead of the raw extracted title.
    """
    rows: list[list[str]] = []
    warnings: list[str] = []
    if config.price_mode == "coefficient" and config.coefficient is None:
        raise ValueError("price_mode 'coefficient' requires a coefficient")

    axis_sources = {axis.source for axis in config.option_axes}
    for product in products:
        if not product.variants:
            warnings.append(f"Réf {product.supplier_ref} : aucune variante — ignorée")
            continue
        if "extra" not in axis_sources:
            # L'extraction peut poser un 3e axe (coupe, longueur…) que le
            # profil ne rend pas : perte silencieuse interdite — on prévient.
            lost = {
                (variant.extra or "").strip()
                for variant in product.variants
                if (variant.extra or "").strip()
            }
            if lost:
                warnings.append(
                    f"Réf {product.supplier_ref} : valeurs d'option 3"
                    f" ({', '.join(sorted(lost))}) perdues au transfert —"
                    " ajouter un 3e axe au profil"
                )
        brand = (
            config.brand_value if config.brand_mode == "fixed" else product.brand or ""
        )
        supplier = config.supplier_label or fallback_supplier or ""
        season = config.season_label or product.season or ""
        # Repli de profil : le genre extrait/édité garde toujours la main.
        gender = product.gender or config.default_gender or ""
        category = product.category or ""
        image_url = product.image_urls[0] if product.image_urls else ""
        # Poids par défaut de la catégorie (table catégorie Xano, décision
        # Marc 2026-07-25) : les fichiers fournisseurs ne portent jamais de
        # poids — repli automatique quand la catégorie en définit un.
        # Poids : celui lu dans le document fournisseur d'abord (Marc
        # 2026-08-22), repli sur le défaut de la catégorie.
        default_weight = product.weight_kg or (category_weights or {}).get(
            category.strip().lower()
        )
        title = product.title or product.supplier_ref
        if config.apply_title_template and title_template:
            values = {
                "brand": brand,
                "title": product.title or "",
                "season": season,
                "reference": product.supplier_ref,
                "color": _product_color(product),
                "category": category,
                "department": gender,
                "composition": product.composition or "",
            }
            title = (
                render_title_template(values, title_template, title_case)
                or product.supplier_ref
            )

        for variant in product.variants:
            if config.size_conversion != "none" and variant.size:
                converted = convert_shoe_size(
                    variant.size, config.size_conversion, gender or None
                )
                if converted != variant.size:
                    # Copie locale : la donnée extraite/stockée reste intacte,
                    # seul le rendu Tillin (option + code-barres) est converti.
                    variant = variant.model_copy(update={"size": converted})
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
            # Colonnes option1..option3 dans l'ordre des axes du profil ;
            # le libellé n'est posé que si la variante porte une valeur.
            options: dict[str, str] = {}
            for index, axis in enumerate(config.option_axes, start=1):
                value = (getattr(variant, axis.source, None) or "").strip()
                options[f"option{index}_name"] = axis.label if value else ""
                options[f"option{index}_value"] = depipe(value)
            rows.append(
                _row(
                    {
                        "title": depipe(title),
                        "reference_code": depipe(product.supplier_ref),
                        **options,
                        "variant_barcode": barcode,
                        "weight": f"{default_weight:g}" if default_weight else "",
                        "weight_unit": "kg" if default_weight else "",
                        "image_url": image_url,
                        "wholesale_price": (
                            format_decimal(variant.wholesale_price)
                            if variant.wholesale_price is not None
                            else ""
                        ),
                        "wholesale_discount": (
                            format_decimal(variant.wholesale_discount)
                            if variant.wholesale_discount is not None
                            else "0"
                        ),
                        "wholesale_tax_rate": config.wholesale_tax_rate,
                        "price": format_decimal(price) if price is not None else "",
                        "tax_rate": config.tax_rate,
                        "gender": gender,
                        "supplier": supplier,
                        "brand": brand,
                        "category": category,
                        "season": season,
                        "composition": product.composition or "",
                        # Tags du profil, appliqués à toutes les lignes
                        # (Marc 2026-08-22) — valeurs séparées par des virgules.
                        "tags": ",".join(
                            dict.fromkeys(
                                tag.strip()
                                for tag in [*config.tags, *product.tags]
                                if tag.strip()
                            )
                        ),
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
