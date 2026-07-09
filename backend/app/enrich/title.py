"""Title templating: `{brand} {title} {season}` -> rendered product title."""

import re

from app.api.schemas import Product
from app.api.schemas.settings import TitleCase

# Tokens the template may reference. `color` is accepted but empty until the
# canonical schema carries variant color options (TODO plan).
TOKENS = ("brand", "title", "season", "reference", "color", "category", "department")


def _token_values(product: Product) -> dict[str, str]:
    return {
        "brand": (product.brand.name if product.brand else None) or "",
        "title": product.title or "",
        "season": product.season or "",
        "reference": product.reference_code or "",
        "color": "",
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
    "ARMEDANGELS"), unlike ``str.capitalize``."""
    if case == "upper":
        return text.upper()
    if case == "capitalize":
        return re.sub(r"\b\w", lambda m: m.group().upper(), text)
    return text


def apply_title_template(
    product: Product, template: str, case: TitleCase = "none"
) -> str:
    """Render a title template; unknown tokens raise, empty values collapse."""
    values = _token_values(product)
    _drop_brand_if_already_in_title(values)

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in values:
            raise ValueError(f"Unknown title template token: {{{token}}}")
        return values[token]

    rendered = re.sub(r"\{(\w+)\}", replace, template)
    return _apply_case(re.sub(r"\s+", " ", rendered).strip(), case)
