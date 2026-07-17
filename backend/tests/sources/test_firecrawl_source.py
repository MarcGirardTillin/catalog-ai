"""Tests for the Firecrawl source adapter (shape + reference matching)."""

from typing import Any

import httpx

from app.api.schemas import Product, ProductVariant
from app.clients.firecrawl import FirecrawlClient
from app.sources.firecrawl_source import (
    extract_source_product,
    merge_extracted_text,
    reference_matches,
)

PRODUCT = Product(
    id=1,
    title="Speedcross 6 Black",
    reference_code="L41737900",
    variants=[
        ProductVariant(id=11, sku="TIL-001", barcode="0193128691234"),
    ],
)


def _client(extracted: dict[str, Any] | None) -> FirecrawlClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        data: dict[str, Any] = {"metadata": {}}
        if extracted is not None:
            data["json"] = extracted
        return httpx.Response(200, json={"success": True, "data": data})

    return FirecrawlClient("fc-key", transport=httpx.MockTransport(handler))


def test_extract_source_product_adapts_to_shopify_shape() -> None:
    with _client(
        {
            "title": "Speedcross 6",
            "description": "Chaussure de trail.",
            "images": ["https://brand.example/img/1.jpg", ""],
            "reference_codes": ["L41737900", "0193128691234"],
            "color": "Black",
        }
    ) as firecrawl:
        adapted = extract_source_product(firecrawl, "https://brand.example/p/1")

    assert adapted == {
        "title": "Speedcross 6",
        "body_html": "Chaussure de trail.",
        "images": [{"src": "https://brand.example/img/1.jpg"}],
        "variants": [],  # no variant data → no weight proposals
        "tags": None,
        "_firecrawl": True,
        "_reference_codes": ["L41737900", "0193128691234"],
        "_color": "Black",
    }


def test_extract_source_product_none_when_no_json() -> None:
    with _client(None) as firecrawl:
        assert extract_source_product(firecrawl, "https://brand.example/p/1") is None


def test_extract_source_product_carries_technical_text_fields() -> None:
    """Les champs techniques (accordéons : caractéristiques, composition,
    pays, entretien) voyagent sous des clés underscore vers le copywriter."""
    with _client(
        {
            "title": "Zero Singlet",
            "description": "Débardeur ultra-léger.",
            "features": ["Matière perforée", "Coutures collées"],
            "composition": "100% polyester recyclé",
            "manufacturing_country": "Vietnam",
            "care": "Lavage à 30°",
        }
    ) as firecrawl:
        adapted = extract_source_product(firecrawl, "https://brand.example/p/2")

    assert adapted is not None
    assert adapted["_features"] == ["Matière perforée", "Coutures collées"]
    assert adapted["_composition"] == "100% polyester recyclé"
    assert adapted["_manufacturing_country"] == "Vietnam"
    assert adapted["_care"] == "Lavage à 30°"


def test_merge_extracted_text_grafts_without_touching_shopify_fields() -> None:
    """Hybride : le texte de la page complète le JSON Shopify — body_html,
    images et variantes (autorité matching/poids) restent intacts."""
    shopify = {
        "title": "Jupe crayon",
        "body_html": "Une phrase.",
        "images": [{"src": "https://cdn/1.jpg"}],
        "variants": [{"sku": "S-1", "barcode": "123"}],
    }
    merged = merge_extracted_text(
        shopify,
        {
            "description": "Description riche de la page.",
            "features": ["Coton stretch", "Imprimé floral"],
            "composition": "97% coton, 3% élasthanne",
            "manufacturing_country": None,  # absent de la page → ignoré
        },
    )
    assert merged["body_html"] == "Une phrase."
    assert merged["variants"] == [{"sku": "S-1", "barcode": "123"}]
    assert merged["_page_description"] == "Description riche de la page."
    assert merged["_features"] == ["Coton stretch", "Imprimé floral"]
    assert merged["_composition"] == "97% coton, 3% élasthanne"
    assert "_manufacturing_country" not in merged
    # L'original n'est pas muté (le pipeline peut le réutiliser).
    assert "_features" not in shopify


def test_placeholder_values_are_filtered_out() -> None:
    """Le LLM d'extraction remplit parfois un champ absent avec « Non
    spécifié » (vu live sur on.com) — jamais transmis au copywriter."""
    merged = merge_extracted_text(
        {"title": "T"},
        {"composition": "Non spécifié", "manufacturing_country": "  N/A "},
    )
    assert "_composition" not in merged
    assert "_manufacturing_country" not in merged


def test_reference_matches_on_reference_code_case_and_spaces() -> None:
    extracted = {"_reference_codes": ["ref. l41 737 900"], "title": "Autre"}
    assert reference_matches(PRODUCT, extracted) is True


def test_reference_matches_on_variant_barcode() -> None:
    extracted = {
        "_reference_codes": [],
        "title": "Speedcross",
        "body_html": "EAN 0193128691234 — trail.",
    }
    assert reference_matches(PRODUCT, extracted) is True


def test_reference_matches_in_title() -> None:
    extracted = {"_reference_codes": [], "title": "Speedcross 6 (L41737900)"}
    assert reference_matches(PRODUCT, extracted) is True


def test_reference_does_not_match_unrelated_page() -> None:
    extracted = {
        "_reference_codes": ["XA-PRO-3D"],
        "title": "XA Pro 3D",
        "body_html": "Autre chaussure.",
    }
    assert reference_matches(PRODUCT, extracted) is False


def test_reference_matches_false_without_identifiers() -> None:
    bare = Product(id=2, title="Sans identifiants")
    assert reference_matches(bare, {"_reference_codes": ["ANY"]}) is False
