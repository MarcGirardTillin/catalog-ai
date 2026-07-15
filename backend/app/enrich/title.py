"""Title templating: `{brand} {title} {season}` -> rendered product title."""

import re

from app.api.schemas import Product
from app.api.schemas.settings import TitleCase

TOKENS = ("brand", "title", "season", "reference", "color", "category", "department")


def _product_color(product: Product) -> str:
    """The product's color, read from its variants' Tillin options.

    Boutique convention: one product = one colorway, so the first non-empty
    variant color is the product color (distinct values are joined just in
    case the data disagrees).
    """
    colors: list[str] = []
    for variant in product.variants:
        color = (variant.color or "").strip()
        if color and color not in colors:
            colors.append(color)
    return " / ".join(colors)


def _token_values(product: Product) -> dict[str, str]:
    return {
        "brand": (product.brand.name if product.brand else None) or "",
        "title": product.title or "",
        "season": product.season or "",
        "reference": product.reference_code or "",
        "color": _product_color(product),
        "category": product.category or "",
        "department": product.department or "",
    }


def _drop_brand_if_already_in_title(values: dict[str, str]) -> None:
    """Blank the `brand` token when the title already contains the brand name.

    Tillin titles often embed the brand (e.g. "ARMEDANGELS Polo rayé…"), which
    would render "ARMEDANGELS ARMEDANGELS Polo rayé…" with `{brand} {title}`.
    Matching is case-insensitive and word-bounded; only applies when both
    values are non-empty.
    """
    brand, title = values["brand"], values["title"]
    if not brand or not title:
        return
    if re.search(rf"(?<!\w){re.escape(brand)}(?!\w)", title, flags=re.IGNORECASE):
        values["brand"] = ""


def _apply_case(text: str, case: TitleCase) -> str:
    """Case the rendered title. `capitalize` upper-cases the first letter of
    each word but leaves the rest untouched (preserves acronyms/brands like
    "ARMEDANGELS"), unlike ``str.capitalize``. `title` is the strict variant:
    it also LOWERS the rest of each word ("ARMEDANGELS" → "Armedangels" — and
    "XL" → "Xl", the assumed trade-off)."""
    if case == "upper":
        return text.upper()
    if case == "capitalize":
        return re.sub(r"\b\w", lambda m: m.group().upper(), text)
    if case == "title":
        return re.sub(r"\b\w", lambda m: m.group().upper(), text.lower())
    return text


def render_title_template(
    values: dict[str, str], template: str, case: TitleCase = "none"
) -> str:
    """Render a title template from an explicit token map.

    Shared core: enrichment builds `values` from a Tillin `Product`
    (:func:`apply_title_template`), imports build them from an
    `ImportedProduct` (`app.imports.tillin_csv`). Unknown tokens raise;
    empty values collapse dangling separators.
    """
    values = dict(values)
    _drop_brand_if_already_in_title(values)

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in values:
            raise ValueError(f"Unknown title template token: {{{token}}}")
        return values[token]

    rendered = re.sub(r"\{(\w+)\}", replace, template)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    # Empty tokens leave dangling separators ("XT-6 - SALOMON -" when {color}
    # is empty): collapse doubled separators and trim them at both ends. Only
    # space-flanked separators are touched, so "XT-6" or "Bleu/Blanc" survive.
    rendered = re.sub(r"(\s[-|•/,])(?:\s[-|•/,])+(?=\s)", r"\1", rendered)
    rendered = re.sub(r"(?:\s[-|•/,])+$", "", rendered)
    rendered = re.sub(r"^(?:[-|•/,]\s)+", "", rendered)
    return _apply_case(rendered.strip(), case)


def apply_title_template(
    product: Product, template: str, case: TitleCase = "none"
) -> str:
    """Render a title template for a Tillin product (enrichment pipeline)."""
    return render_title_template(_token_values(product), template, case)
