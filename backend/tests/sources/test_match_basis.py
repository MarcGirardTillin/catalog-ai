"""Information de rapprochement fiche source ↔ produit Tillin."""

from app.api.schemas import Product, ProductVariant
from app.sources.match_basis import match_basis

PRODUCT = Product(
    id=1,
    title="Peluche Bunny small",
    reference_code="BN-12",
    variants=[ProductVariant(id=11, sku="TIL-001", barcode="3760000000017")],
)


def test_barcode_on_a_shopify_variant() -> None:
    source = {"title": "Bunny", "variants": [{"barcode": "3760000000017"}]}
    assert match_basis(PRODUCT, source) == "barcode"


def test_barcode_in_extracted_codes() -> None:
    source = {"title": "Bunny", "_reference_codes": ["EAN 3760000000017"]}
    assert match_basis(PRODUCT, source) == "barcode"


def test_reference_formatting_insensitive() -> None:
    source = {"title": "Peluche", "variants": [{"sku": "bn12-small"}]}
    assert match_basis(PRODUCT, source) == "reference"


def test_title_when_no_identifier() -> None:
    source = {"title": "Peluche Bunny small", "body_html": "<p>Douce</p>"}
    assert match_basis(PRODUCT, source) == "title"
