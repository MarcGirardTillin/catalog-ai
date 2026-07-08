"""Tests for the composed enrichment pipeline (worker processor)."""

from typing import Any

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import Brand, Product, ProductVariant
from app.enrich.pipeline import EnrichmentPipeline
from app.jobs.worker import process_one
from app.models import Account, EnrichmentItem, EnrichmentJob

SITE = "https://gramicci.example"

PRODUCT = Product(
    id=101,
    title="G-Short Double Navy",
    reference_code="G5FU-T081",
    brand=Brand(id=7, name="Gramicci", website_urls=[SITE]),
    season="SS25",
    variants=[
        ProductVariant(id=11, sku="TIL-001", barcode="4550479812345"),
        ProductVariant(id=12, sku="TIL-002", barcode="4550479812352"),
    ],
)

SOURCE_PRODUCT = {
    "title": "G-Short Double Navy",
    "handle": "g-short-double-navy",
    "tags": "shorts, ss25",
    "body_html": "<p>Le short d'origine.</p>",
    "variants": [
        {"sku": "G5FU-T081-M", "barcode": "4550479812345", "grams": 320},
        {"sku": "G5FU-T081-L", "barcode": "4550479812352", "grams": 340},
    ],
    "images": [
        {"src": f"{SITE}/cdn/1.jpg"},
        {"src": f"{SITE}/cdn/2.jpg"},
    ],
}


def _store(catalog: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    """Fake Shopify store (same shape as the resolver tests)."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/suggest.json":
            query = request.url.params["q"].lower()
            hits = [
                {"handle": handle, "title": product["title"]}
                for handle, product in catalog.items()
                if query in product["title"].lower()
                or any(
                    query == str(v.get("barcode", "")).lower()
                    for v in product["variants"]
                )
            ]
            return httpx.Response(
                200, json={"resources": {"results": {"products": hits}}}
            )
        if path.startswith("/products/") and path.endswith(".json"):
            handle = path.removeprefix("/products/").removesuffix(".json")
            if handle in catalog:
                return httpx.Response(200, json={"product": catalog[handle]})
            return httpx.Response(404)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _seed_item(
    db: Session, product_id: int, config: dict[str, Any] | None = None
) -> EnrichmentItem:
    account = Account(name="default")
    db.add(account)
    db.flush()
    job = EnrichmentJob(
        account_id=account.id, selection_json={}, config_json=config or {}
    )
    db.add(job)
    db.flush()
    item = EnrichmentItem(
        job_id=job.id, account_id=account.id, tillin_product_id=product_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


class _FakeClaude:
    """Stands in for ClaudeClient.generate_copy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_copy(
        self,
        product_ctx: dict[str, Any],
        *,
        editorial_instructions: str = "",
        model: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "ctx": product_ctx,
                "instructions": editorial_instructions,
                "model": model,
            }
        )

        class _Copy:
            description_fr = "Un short robuste et léger."
            meta_description_fr = "Short Gramicci G-Short — confort et style."

        return _Copy()


def test_pipeline_stages_title_weights_images_and_copy(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    claude = _FakeClaude()

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid: PRODUCT,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.status == "ready_for_review"
    assert item.staged_title == "Gramicci G-Short Double Navy"
    assert item.source_url == f"{SITE}/products/g-short-double-navy"
    assert item.source_method == "shopify_json"
    assert item.match_score == 1.0
    assert item.staged_weights_json == [
        {"variant_id": 11, "weight": 0.32, "weight_unit": "kg"},
        {"variant_id": 12, "weight": 0.34, "weight_unit": "kg"},
    ]
    assert item.staged_images_json == [
        {"url": f"{SITE}/cdn/1.jpg", "position": 1},
        {"url": f"{SITE}/cdn/2.jpg", "position": 2},
    ]
    assert item.staged_description == "Un short robuste et léger."
    assert item.staged_meta is not None
    # The copywriter saw both canonical and source-page facts.
    assert claude.calls[0]["ctx"]["brand"] == "Gramicci"
    assert "source_description_html" in claude.calls[0]["ctx"]
    db.close()


def test_pipeline_without_claude_and_without_brand_site(
    db_session_factory: sessionmaker[Session],
) -> None:
    """Degraded mode: no AI key, product without brand website."""
    db = db_session_factory()
    item = _seed_item(db, 999, config={"title_template": "{brand} {title} {season}"})
    bare = Product(id=999, title="Produit 999")

    with httpx.Client(transport=_store({})) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid: bare, http_client=http_client
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.status == "ready_for_review"
    assert item.staged_title == "Produit 999"  # empty tokens collapse
    assert item.source_method == "skipped"
    assert item.source_url is None
    assert item.staged_description is None
    assert item.staged_weights_json is None
    db.close()


def test_pipeline_persists_resolution_candidates(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid: PRODUCT, http_client=http_client
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.resolution_json is not None
    candidates = item.resolution_json["candidates"]
    assert candidates and candidates[0]["score"] == 1.0
    assert candidates[0]["url"] == f"{SITE}/products/g-short-double-navy"
    db.close()


def test_stage_from_url_manually_restages(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, PRODUCT.id)
    item.status = "ready_for_review"
    item.source_method = "needs_manual"
    db.commit()
    claude = _FakeClaude()

    with httpx.Client(
        transport=_store({"g-short-double-navy": SOURCE_PRODUCT})
    ) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid: PRODUCT,
            http_client=http_client,
            claude=claude,  # type: ignore[arg-type]
        )
        pipeline.stage_from_url(item, f"{SITE}/products/g-short-double-navy")

    db.commit()
    db.refresh(item)
    assert item.source_method == "manual"
    assert item.source_url == f"{SITE}/products/g-short-double-navy"
    assert item.match_score == 1.0
    assert item.staged_images_json == [
        {"url": f"{SITE}/cdn/1.jpg", "position": 1},
        {"url": f"{SITE}/cdn/2.jpg", "position": 2},
    ]
    assert item.staged_description == "Un short robuste et léger."
    db.close()


def test_pipeline_missing_product_fails_item(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    item = _seed_item(db, 404)

    with httpx.Client(transport=_store({})) as http_client:
        pipeline = EnrichmentPipeline(
            read_product=lambda _pid: None, http_client=http_client
        )
        assert process_one(db, pipeline) is True

    db.refresh(item)
    assert item.status == "pending"  # requeued (attempt 1 of MAX_ATTEMPTS)
    assert item.error is not None
    assert "not found" in item.error
    db.close()
