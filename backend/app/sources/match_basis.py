"""Quelle information a permis de rapprocher une fiche source du produit
Tillin : code-barres, référence ou, à défaut, le titre.

Même hiérarchie que les scores (``shopify_json.score_product_match``,
``firecrawl_source.reference_matches``), mais le score seul ne la porte pas :
0.9 vaut « barcode ou référence » sur une page extraite. Affiché dans la
liste du job et la review (Marc 2026-10-08).
"""

from typing import Any, Literal

from app.api.schemas import Product
from app.sources.shopify_json import reference_key

MatchBasis = Literal["barcode", "reference", "title"]


def _texts(source: dict[str, Any]) -> list[str]:
    variants = source.get("variants") or []
    values: list[Any] = [
        *(source.get("_reference_codes") or []),
        source.get("title"),
        source.get("body_html"),
        source.get("handle"),
        source.get("tags"),
        *(v.get("sku") for v in variants if isinstance(v, dict)),
    ]
    return [key for key in (reference_key(v) for v in values) if key]


def match_basis(product: Product, source: dict[str, Any]) -> MatchBasis:
    """Code-barres d'une variante (exact sur les variantes de la fiche, ou
    présent dans ses codes/texte), sinon référence, sinon titre."""
    texts = _texts(source)
    barcodes = {reference_key(v.barcode) for v in product.variants if v.barcode}
    barcodes.discard("")
    source_barcodes = {
        reference_key(v.get("barcode"))
        for v in source.get("variants") or []
        if isinstance(v, dict) and v.get("barcode")
    }
    if barcodes & source_barcodes or any(
        code in text for code in barcodes for text in texts
    ):
        return "barcode"
    reference = reference_key(product.reference_code)
    if reference and any(reference in text for text in texts):
        return "reference"
    return "title"
