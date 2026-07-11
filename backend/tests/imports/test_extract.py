"""Tests for the ClaudeExtractor (transport fully mocked, no real API)."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import anthropic
import httpx
import pytest

from app.clients.base import ExternalServiceError, NotConfiguredError
from app.imports.extract import ClaudeExtractor, build_extractor, ean13_is_valid
from app.imports.schema import Extractor, RawDocument, RawTable

VALID_EAN = "3607814866838"
INVALID_EAN = "3607814866839"  # wrong check digit

Handler = Callable[[httpx.Request], httpx.Response]


def _api_response(
    payload: dict[str, Any],
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-sonnet-5",
    raw_text: str | None = None,
) -> dict[str, Any]:
    text = raw_text if raw_text is not None else json.dumps(payload)
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def _extractor(handler: Handler) -> Extractor:
    return build_extractor(
        "sk-test",
        http_client=anthropic.DefaultHttpxClient(
            transport=httpx.MockTransport(handler)
        ),
    )


def _tabular_document() -> RawDocument:
    return RawDocument(
        kind="tabular",
        filename="commande.xlsx",
        tables=[
            RawTable(
                sheet="Commande",
                rows=[
                    [
                        "Référence",
                        "Désignation",
                        "Coloris",
                        "Taille",
                        "EAN",
                        "PA HT",
                        "PVP",
                    ],
                    [
                        "REF001",
                        "Robe fleurie",
                        "Rouge",
                        "36",
                        VALID_EAN,
                        "39,90",
                        "89,00",
                    ],
                ],
            )
        ],
    )


# Wire format is union-free: strings everywhere, "" = absent (the live API
# caps union-typed schema parameters at 16 — a fully nullable schema is
# rejected with a 400, which mocks can't catch).
def _payload(
    *,
    ean: str = VALID_EAN,
    wholesale: str = "39.9",
    retail: str = "89",
    po_number: str = "PO-12345",
    supplier: str = "L'Espion",
) -> dict[str, Any]:
    return {
        "po_number": po_number,
        "supplier": supplier,
        "products": [
            {
                "supplier_ref": "REF001",
                "title": "Robe fleurie",
                "brand": "",
                "confidence": {"title": 0.95, "brand": 0.0},
                "variants": [
                    {
                        "ean": ean,
                        "color": "Rouge",
                        "size": "36",
                        "quantity": "1",
                        "wholesale_price": wholesale,
                        "retail_price": retail,
                        "supplier_sku": "",
                        "confidence": {"ean": 0.8, "wholesale_price": 0.7},
                    }
                ],
            }
        ],
    }


def test_tabular_extraction_maps_and_verifies_values() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_api_response(_payload()))

    result = _extractor(handler)(_tabular_document())

    assert result.warnings == []
    # Document-level facts (purchase order header).
    assert result.document.po_number == "PO-12345"
    assert result.document.supplier == "L'Espion"
    product = result.products[0]
    assert product.supplier_ref == "REF001"
    assert product.title == "Robe fleurie"
    assert product.brand is None  # "" mapped back to None
    assert product.confidence == {"title": 0.95}  # empty-field confidences dropped
    variant = product.variants[0]
    assert variant.ean == VALID_EAN
    assert variant.color == "Rouge"
    assert variant.size == "36"
    assert variant.quantity == 1
    # "39.9" matches the source cell "39,90" (comma + trailing zero tolerated).
    assert variant.wholesale_price == Decimal("39.9")
    assert variant.retail_price == Decimal("89")
    # Verified values are promoted to confidence 1.0.
    assert variant.confidence["ean"] == 1.0
    assert variant.confidence["wholesale_price"] == 1.0
    assert variant.confidence["retail_price"] == 1.0

    # Usage is filled from the API response.
    assert len(result.usage) == 1
    assert result.usage[0].model == "claude-sonnet-5"
    assert result.usage[0].input_tokens == 100
    assert result.usage[0].output_tokens == 50

    # Request shape: structured output + serialized tables in the content.
    body = json.loads(captured["request"].content)
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "bon de commande" in body["system"]
    text = body["messages"][0]["content"][0]["text"]
    assert "Feuille : Commande" in text
    assert VALID_EAN in text


def test_document_info_empty_strings_map_to_none() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _payload(po_number="", supplier="  ")
        return httpx.Response(200, json=_api_response(payload))

    result = _extractor(handler)(_tabular_document())
    assert result.document.po_number is None
    assert result.document.supplier is None


def _category_payload(category: str) -> dict[str, Any]:
    return {
        "po_number": "",
        "supplier": "",
        "products": [
            {
                "supplier_ref": "REF001",
                "title": "Robe fleurie",
                "brand": "",
                "category": category,
                "confidence": {},
                "variants": [],
            }
        ],
    }


def _extractor_with_categories(handler: Handler, categories: list[str]) -> Extractor:
    return build_extractor(
        "sk-test",
        http_client=anthropic.DefaultHttpxClient(
            transport=httpx.MockTransport(handler)
        ),
        known_categories=categories,
    )


def test_known_categories_are_injected_into_prompt() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_api_response(_category_payload("")))

    tree = ["VETEMENTS > Robes", "ACCESSOIRES > Bijoux > Bracelet"]
    _extractor_with_categories(handler, tree)(_tabular_document())

    text = json.loads(captured["request"].content)["messages"][0]["content"][0]["text"]
    assert "Catégories existantes" in text
    assert "VETEMENTS > Robes" in text
    assert "ACCESSOIRES > Bijoux > Bracelet" in text


def test_extracted_category_is_canonicalized_to_the_tree() -> None:
    # Model echoes a lowercase leaf; it is rewritten to the tree's casing.
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_api_response(_category_payload("robes")))

    result = _extractor_with_categories(handler, ["VETEMENTS > Robes"])(
        _tabular_document()
    )
    product = result.products[0]
    assert product.category == "Robes"
    assert product.confidence["category"] == 1.0


def test_unmatched_category_is_kept_verbatim() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_api_response(_category_payload("Chaussettes")))

    result = _extractor_with_categories(handler, ["VETEMENTS > Robes"])(
        _tabular_document()
    )
    # No confident tree match -> raw label preserved for manual mapping.
    assert result.products[0].category == "Chaussettes"


def test_tabular_cross_check_removes_unverifiable_values() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _payload(ean="9999999999994", wholesale="12.34")
        return httpx.Response(200, json=_api_response(payload))

    result = _extractor(handler)(_tabular_document())

    variant = result.products[0].variants[0]
    assert variant.ean is None
    assert variant.confidence["ean"] == 0.0
    assert variant.wholesale_price is None
    assert variant.confidence["wholesale_price"] == 0.0
    # Retail price was verifiable and kept.
    assert variant.retail_price == Decimal("89")
    assert any("EAN 9999999999994 introuvable" in w for w in result.warnings)
    assert any("12.34" in w and "introuvable" in w for w in result.warnings)


def test_tabular_unparseable_price_is_removed_with_warning() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_api_response(_payload(wholesale="N/A")))

    result = _extractor(handler)(_tabular_document())

    variant = result.products[0].variants[0]
    assert variant.wholesale_price is None
    assert variant.confidence["wholesale_price"] == 0.0
    assert any("Prix illisible" in w for w in result.warnings)


def test_pdf_extraction_sends_document_block_and_checks_ean13() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_api_response(_payload()))

    document = RawDocument(
        kind="pdf", filename="commande.pdf", pdf_bytes=b"%PDF-1.4 fake"
    )
    result = _extractor(handler)(document)

    body = json.loads(captured["request"].content)
    block = body["messages"][0]["content"][0]
    assert block["type"] == "document"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "application/pdf"

    variant = result.products[0].variants[0]
    # Valid EAN-13 checksum: kept, model confidence preserved (not forced to 1).
    assert variant.ean == VALID_EAN
    assert variant.confidence["ean"] == 0.8
    # PDF prices keep the model's confidence.
    assert variant.wholesale_price == Decimal("39.9")
    assert variant.confidence["wholesale_price"] == 0.7
    assert result.warnings == []


def test_pdf_invalid_ean13_is_removed() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_api_response(_payload(ean=INVALID_EAN)))

    document = RawDocument(
        kind="pdf", filename="commande.pdf", pdf_bytes=b"%PDF-1.4 fake"
    )
    result = _extractor(handler)(document)

    variant = result.products[0].variants[0]
    assert variant.ean is None
    assert variant.confidence["ean"] == 0.0
    assert any(INVALID_EAN in w and "EAN-13" in w for w in result.warnings)


def test_max_tokens_stop_reason_adds_truncation_warning() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_api_response(_payload(), stop_reason="max_tokens")
        )

    result = _extractor(handler)(_tabular_document())
    assert any("tronquée" in w for w in result.warnings)


def test_refusal_and_invalid_json_raise() -> None:
    def refusal(_: httpx.Request) -> httpx.Response:
        payload = _api_response({}, stop_reason="refusal")
        payload["content"] = []
        return httpx.Response(200, json=payload)

    with pytest.raises(ExternalServiceError):
        _extractor(refusal)(_tabular_document())

    def bad_json(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_api_response({}, raw_text="not json"))

    with pytest.raises(ExternalServiceError):
        _extractor(bad_json)(_tabular_document())


def test_upstream_error_raises_external_service_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"type": "error", "error": {"type": "api_error", "message": "boom"}},
        )

    with pytest.raises(ExternalServiceError):
        _extractor(handler)(_tabular_document())


def test_huge_tabular_source_is_truncated_with_warning() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_api_response({"products": []}))

    rows = [["REF", str(i)] for i in range(2500)]
    document = RawDocument(
        kind="tabular",
        filename="huge.csv",
        tables=[RawTable(rows=rows, sheet=None)],
    )
    result = _extractor(handler)(document)

    assert any("tronquée à 2000 lignes" in w for w in result.warnings)
    text = json.loads(captured["request"].content)["messages"][0]["content"][0]["text"]
    assert "REF\t1999" in text
    assert "REF\t2000" not in text


SECOND_EAN = "4006381333931"  # valid EAN-13, distinct from VALID_EAN


def _second_tabular_document() -> RawDocument:
    return RawDocument(
        kind="tabular",
        filename="codes.csv",
        tables=[RawTable(sheet=None, rows=[["ref", "ean"], ["REF002", SECOND_EAN]])],
    )


def _one_variant_payload(**variant: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ean": "",
        "color": "",
        "size": "",
        "quantity": "",
        "wholesale_price": "",
        "retail_price": "",
        "supplier_sku": "",
        "confidence": {"ean": 0.5},
    }
    base.update(variant)
    return {
        "po_number": "PO-1",
        "supplier": "L'Espion",
        "products": [
            {
                "supplier_ref": "REF002",
                "title": "Veste",
                "brand": "",
                "confidence": {},
                "variants": [base],
            }
        ],
    }


def test_single_element_list_is_byte_identical_to_mono() -> None:
    requests: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.content)
        return httpx.Response(200, json=_api_response(_payload()))

    mono = _extractor(handler)(_tabular_document())
    listed = _extractor(handler)([_tabular_document()])

    # Same request on the wire and same extraction: a one-element list is the
    # historical single-file path.
    assert requests[0] == requests[1]
    assert listed.model_dump() == mono.model_dump()


def test_multi_tabular_is_one_call_over_the_union() -> None:
    captured: dict[str, httpx.Request] = {}
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        captured["request"] = request
        # The EAN only exists in the SECOND file's cells.
        return httpx.Response(
            200, json=_api_response(_one_variant_payload(ean=SECOND_EAN))
        )

    result = _extractor(handler)([_tabular_document(), _second_tabular_document()])

    # A single Claude call carrying BOTH files.
    assert calls == [1]
    content = json.loads(captured["request"].content)["messages"][0]["content"]
    joined = "\n".join(block["text"] for block in content if block["type"] == "text")
    assert "MÊME bon de commande" in joined
    assert "commande.xlsx" in joined
    assert "codes.csv" in joined
    assert SECOND_EAN in joined

    # EAN found only in the 2nd file's cells is kept and promoted to 1.0.
    variant = result.products[0].variants[0]
    assert variant.ean == SECOND_EAN
    assert variant.confidence["ean"] == 1.0


def test_multi_pdf_plus_tabular_validates_ean_by_check_digit() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        # VALID_EAN is a valid EAN-13 but is NOT in the tabular file's cells.
        return httpx.Response(
            200,
            json=_api_response(_payload(ean=VALID_EAN, wholesale="39.9", retail="89")),
        )

    pdf = RawDocument(kind="pdf", filename="order.pdf", pdf_bytes=b"%PDF-1.4 fake")
    tabular = RawDocument(
        kind="tabular",
        filename="other.csv",
        tables=[RawTable(sheet=None, rows=[["ref"], ["REF001"]])],
    )
    result = _extractor(handler)([pdf, tabular])

    variant = result.products[0].variants[0]
    # Absent from the tabular pool, but the lot has a PDF -> check digit saves it.
    assert variant.ean == VALID_EAN
    assert variant.confidence["ean"] == 0.8  # model confidence preserved
    # Prices are validated against the tabular pool (present here) -> removed.
    assert variant.wholesale_price is None
    assert variant.retail_price is None


def test_multi_pdf_plus_tabular_drops_invalid_check_digit_ean() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_api_response(_payload(ean=INVALID_EAN)))

    pdf = RawDocument(kind="pdf", filename="order.pdf", pdf_bytes=b"%PDF-1.4 fake")
    tabular = RawDocument(
        kind="tabular",
        filename="other.csv",
        tables=[RawTable(sheet=None, rows=[["ref"], ["REF001"]])],
    )
    result = _extractor(handler)([pdf, tabular])

    variant = result.products[0].variants[0]
    assert variant.ean is None
    assert variant.confidence["ean"] == 0.0
    assert any("EAN-13" in w for w in result.warnings)


def test_multi_all_pdf_keeps_model_price_confidence() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_api_response(_payload()))

    first = RawDocument(kind="pdf", filename="a.pdf", pdf_bytes=b"%PDF-1.4 a")
    second = RawDocument(kind="pdf", filename="b.pdf", pdf_bytes=b"%PDF-1.4 b")
    result = _extractor(handler)([first, second])

    variant = result.products[0].variants[0]
    # No tabular pool: prices survive with the model's own confidence.
    assert variant.wholesale_price == Decimal("39.9")
    assert variant.confidence["wholesale_price"] == 0.7
    assert variant.ean == VALID_EAN


def test_build_extractor_requires_api_key() -> None:
    with pytest.raises(NotConfiguredError):
        build_extractor("")
    with pytest.raises(NotConfiguredError):
        ClaudeExtractor("")


def test_parse_decimal_handles_separator_conventions() -> None:
    """Regression: '1,143.00' (thousands separator) was rejected on a real
    L'Espion PDF. Both conventions and mixed forms must parse."""
    from app.imports.extract import _parse_decimal

    assert _parse_decimal("39,90") == Decimal("39.90")
    assert _parse_decimal("24.5") == Decimal("24.5")
    assert _parse_decimal("1,143.00") == Decimal("1143.00")
    assert _parse_decimal("1.250,00") == Decimal("1250.00")
    assert _parse_decimal("1 250,00 €") == Decimal("1250.00")
    assert _parse_decimal("1,143") == Decimal("1143")  # single sep, 3 digits
    assert _parse_decimal("1.234.567") == Decimal("1234567")
    assert _parse_decimal("430.00") == Decimal("430.00")
    assert _parse_decimal("N/A") is None
    assert _parse_decimal("") is None


def test_extraction_schema_stays_union_free() -> None:
    """The live API rejects schemas with > 16 union-typed parameters
    ("exponential compilation cost", 400). Ours must stay at ZERO —
    absent values travel as "" instead of null."""
    from app.imports.extract import EXTRACTION_SCHEMA

    def count_unions(node: Any) -> int:
        if isinstance(node, dict):
            unions = 1 if "anyOf" in node or isinstance(node.get("type"), list) else 0
            return unions + sum(count_unions(child) for child in node.values())
        if isinstance(node, list):
            return sum(count_unions(child) for child in node)
        return 0

    assert count_unions(EXTRACTION_SCHEMA) == 0


def test_ean13_checksum() -> None:
    assert ean13_is_valid(VALID_EAN)
    assert ean13_is_valid("4006381333931")
    assert not ean13_is_valid(INVALID_EAN)
    assert not ean13_is_valid("123")  # too short
    assert not ean13_is_valid("36078148668EA")  # non-digits
