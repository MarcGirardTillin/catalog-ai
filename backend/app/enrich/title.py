"""Title templating: `{brand} {title} {season}` -> rendered product title."""

import re

from app.api.schemas import Product

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


def apply_title_template(product: Product, template: str) -> str:
    """Render a title template; unknown tokens raise, empty values collapse."""
    values = _token_values(product)

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in values:
            raise ValueError(f"Unknown title template token: {{{token}}}")
        return values[token]

    rendered = re.sub(r"\{(\w+)\}", replace, template)
    return re.sub(r"\s+", " ", rendered).strip()
