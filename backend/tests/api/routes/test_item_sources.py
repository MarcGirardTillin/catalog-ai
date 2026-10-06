"""Fiches source supplémentaires « par couleur » d'un item d'enrichissement.

Pipeline RÉEL (logique de fusion des images), seule la récupération de page
(`_fetch_source_from_url`) est remplacée par un faux — aucun appel réseau.
"""

from collections.abc import Generator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.schemas import Product
from app.enrich.pipeline import EnrichmentPipeline
from app.models import Account, EnrichmentItem, EnrichmentJob

MAIN = "https://brand.example/products/bunny-small-pink"
BLUE = "https://brand.example/products/bunny-small-blue"
GREEN = "https://brand.example/products/bunny-small-green"

PAGES: dict[str, dict[str, Any]] = {
    MAIN: {
        "title": "Bunny small pink",
        "images": [{"src": "https://cdn.example/pink-1.jpg"}],
        "variants": [],
    },
    BLUE: {
        "title": "Bunny small blue",
        "images": [
            {"src": "https://cdn.example/blue-1.jpg"},
            {"src": "https://cdn.example/blue-2.jpg"},
            # Image commune déjà stagée par la fiche principale : dédupliquée.
            {"src": "https://cdn.example/pink-1.jpg"},
            # Junk filtré.
            {"src": "https://i.ytimg.com/vi/x/hqdefault.jpg"},
        ],
        "variants": [],
    },
    GREEN: {
        "title": "Bunny small green",
        "images": [{"src": "https://cdn.example/green-1.jpg"}],
        "variants": [],
    },
}


class _Pipeline(EnrichmentPipeline):
    fetched: list[str]

    def _fetch_source_from_url(
        self,
        db: Any,
        item: EnrichmentItem,
        product: Product,
        config: dict[str, Any],
        url: str,
        *,
        enrich_text: bool = True,
    ) -> tuple[dict[str, Any], float]:
        self.fetched.append(url)
        if url not in PAGES:
            raise LookupError(f"no product page at {url}")
        return dict(PAGES[url]), 0.9


@pytest.fixture
def pipeline() -> Generator[_Pipeline]:
    from app.api.deps import get_enrichment_pipeline
    from app.main import app

    instance = _Pipeline(
        read_product=lambda pid, _account, _launcher: Product(
            id=pid, title="Peluche Bunny small"
        ),
        http_client=httpx.Client(),
    )
    instance.fetched = []
    app.dependency_overrides[get_enrichment_pipeline] = lambda: instance
    try:
        yield instance
    finally:
        app.dependency_overrides.pop(get_enrichment_pipeline, None)


def _db() -> Session:
    from app.api.deps import get_db
    from app.main import app

    # Le générateur reste référencé : sa collecte fermerait la session (et
    # détacherait les objets) en plein test.
    gen = app.dependency_overrides[get_db]()
    _SESSIONS.append(gen)
    db: Session = next(gen)
    return db


_SESSIONS: list[Any] = []


def _review_item(auth_client: TestClient, product_id: int = 777) -> EnrichmentItem:
    """Item en review sur la fiche principale MAIN (1 image stagée)."""
    job = auth_client.post("/jobs", json={"selection": {"ids": [product_id]}}).json()
    db = _db()
    item = db.query(EnrichmentItem).filter_by(job_id=job["id"]).one()
    item.status = "ready_for_review"
    item.source_url = MAIN
    item.staged_images_json = [{"url": "https://cdn.example/pink-1.jpg", "position": 1}]
    item.resolution_json = {"reason": None, "candidates": [{"url": BLUE}]}
    db.commit()
    return item


def _urls(body: dict[str, Any]) -> list[str]:
    return [e["url"] for e in body["staged_images_json"] or []]


@pytest.mark.usefixtures("pipeline")
def test_add_extra_source_appends_tagged_images(auth_client: TestClient) -> None:
    item = _review_item(auth_client)

    resp = auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Bleu"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["staged_images_json"] == [
        {"url": "https://cdn.example/pink-1.jpg", "position": 1},
        {
            "url": "https://cdn.example/blue-1.jpg",
            "position": 2,
            "color": "Bleu",
            "source_page": BLUE,
        },
        {
            "url": "https://cdn.example/blue-2.jpg",
            "position": 3,
            "color": "Bleu",
            "source_page": BLUE,
        },
    ]
    assert body["resolution_json"]["extra_sources"] == [
        {"url": BLUE, "color": "Bleu", "title": "Bunny small blue"}
    ]
    # La fiche principale reste l'autorité (source, copie…).
    assert body["source_url"] == MAIN


@pytest.mark.usefixtures("pipeline")
def test_add_extra_source_extends_partial_apply_selection(
    auth_client: TestClient,
) -> None:
    item = _review_item(auth_client)
    db = _db()
    row = db.get(EnrichmentItem, item.id)
    assert row is not None
    row.apply_fields_json = {"title": True, "image_urls": []}
    db.commit()

    body = auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Bleu"}
    ).json()
    assert body["apply_fields_json"]["image_urls"] == [
        "https://cdn.example/blue-1.jpg",
        "https://cdn.example/blue-2.jpg",
    ]

    body = auth_client.delete(
        f"/items/{item.id}/sources", params={"source_url": BLUE}
    ).json()
    assert body["apply_fields_json"]["image_urls"] == []


@pytest.mark.usefixtures("pipeline")
def test_same_url_replaces_its_images_and_color(auth_client: TestClient) -> None:
    item = _review_item(auth_client)
    auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Bleu"}
    )
    body = auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Marine"}
    ).json()

    assert _urls(body) == [
        "https://cdn.example/pink-1.jpg",
        "https://cdn.example/blue-1.jpg",
        "https://cdn.example/blue-2.jpg",
    ]
    assert [e.get("color") for e in body["staged_images_json"]] == [
        None,
        "Marine",
        "Marine",
    ]
    assert body["resolution_json"]["extra_sources"] == [
        {"url": BLUE, "color": "Marine", "title": "Bunny small blue"}
    ]


@pytest.mark.usefixtures("pipeline")
def test_remove_extra_source_drops_images_and_renumbers(
    auth_client: TestClient,
) -> None:
    item = _review_item(auth_client)
    auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Bleu"}
    )
    auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": GREEN, "color": "Vert"}
    )

    resp = auth_client.delete(f"/items/{item.id}/sources", params={"source_url": BLUE})
    assert resp.status_code == 200
    body = resp.json()
    assert [(e["url"], e["position"]) for e in body["staged_images_json"]] == [
        ("https://cdn.example/pink-1.jpg", 1),
        ("https://cdn.example/green-1.jpg", 2),
    ]
    assert [s["url"] for s in body["resolution_json"]["extra_sources"]] == [GREEN]

    unknown = auth_client.delete(
        f"/items/{item.id}/sources", params={"source_url": BLUE}
    )
    assert unknown.status_code == 404


@pytest.mark.usefixtures("pipeline")
def test_extra_source_errors(auth_client: TestClient) -> None:
    item = _review_item(auth_client)

    # La fiche principale ne peut pas être ajoutée comme supplémentaire.
    same = auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": MAIN, "color": "Rose"}
    )
    assert same.status_code == 422
    assert same.json()["code"] == "same_as_main_source"

    dead = auth_client.post(
        f"/items/{item.id}/sources",
        json={"source_url": "https://brand.example/products/dead", "color": "Rose"},
    )
    assert dead.status_code == 422
    assert dead.json()["code"] == "unresolvable_source"

    bad = auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": "nope", "color": "Rose"}
    )
    assert bad.status_code == 422
    blank = auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "  "}
    )
    assert blank.status_code == 422


def test_extra_sources_require_review_state(
    auth_client: TestClient, pipeline: _Pipeline
) -> None:
    item = _review_item(auth_client)
    db = _db()
    row = db.get(EnrichmentItem, item.id)
    assert row is not None
    row.status = "applied"
    db.commit()

    assert (
        auth_client.post(
            f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Bleu"}
        ).status_code
        == 409
    )
    assert (
        auth_client.delete(
            f"/items/{item.id}/sources", params={"source_url": BLUE}
        ).status_code
        == 409
    )
    assert (
        auth_client.put(
            f"/items/{item.id}/main-color", json={"color": "Rose"}
        ).status_code
        == 409
    )
    assert pipeline.fetched == []


def test_extra_sources_scoped_to_account(
    auth_client: TestClient, pipeline: _Pipeline
) -> None:
    db = _db()
    other = Account(name="autre-boutique")
    db.add(other)
    db.flush()
    job = EnrichmentJob(account_id=other.id, selection_json={}, config_json={})
    db.add(job)
    db.flush()
    foreign = EnrichmentItem(
        job_id=job.id,
        account_id=other.id,
        tillin_product_id=1,
        status="ready_for_review",
        source_url=MAIN,
        resolution_json={"extra_sources": [{"url": BLUE, "color": "Bleu"}]},
    )
    db.add(foreign)
    db.commit()

    assert (
        auth_client.post(
            f"/items/{foreign.id}/sources", json={"source_url": GREEN, "color": "Vert"}
        ).status_code
        == 404
    )
    assert (
        auth_client.delete(
            f"/items/{foreign.id}/sources", params={"source_url": BLUE}
        ).status_code
        == 404
    )
    assert (
        auth_client.put(
            f"/items/{foreign.id}/main-color", json={"color": "Rose"}
        ).status_code
        == 404
    )
    assert pipeline.fetched == []


@pytest.mark.usefixtures("pipeline")
def test_main_color_tags_main_images_only(auth_client: TestClient) -> None:
    item = _review_item(auth_client)
    auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Bleu"}
    )

    body = auth_client.put(
        f"/items/{item.id}/main-color", json={"color": "Rose"}
    ).json()
    assert body["resolution_json"]["main_color"] == "Rose"
    assert [e.get("color") for e in body["staged_images_json"]] == [
        "Rose",
        "Bleu",
        "Bleu",
    ]

    cleared = auth_client.put(
        f"/items/{item.id}/main-color", json={"color": None}
    ).json()
    assert "main_color" not in cleared["resolution_json"]
    assert [e.get("color") for e in cleared["staged_images_json"]] == [
        None,
        "Bleu",
        "Bleu",
    ]


@pytest.mark.usefixtures("pipeline")
def test_resolve_keeps_extra_sources(auth_client: TestClient) -> None:
    item = _review_item(auth_client)
    auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": BLUE, "color": "Bleu"}
    )
    auth_client.put(f"/items/{item.id}/main-color", json={"color": "Vert"})

    resp = auth_client.post(f"/items/{item.id}/resolve", json={"source_url": GREEN})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_url"] == GREEN
    assert body["staged_images_json"] == [
        {"url": "https://cdn.example/green-1.jpg", "position": 1, "color": "Vert"},
        {
            "url": "https://cdn.example/blue-1.jpg",
            "position": 2,
            "color": "Bleu",
            "source_page": BLUE,
        },
        {
            "url": "https://cdn.example/blue-2.jpg",
            "position": 3,
            "color": "Bleu",
            "source_page": BLUE,
        },
    ]
    assert [s["url"] for s in body["resolution_json"]["extra_sources"]] == [BLUE]
    assert body["resolution_json"]["main_color"] == "Vert"

    # Une fiche supplémentaire promue fiche principale quitte la liste.
    promoted = auth_client.post(
        f"/items/{item.id}/resolve", json={"source_url": BLUE}
    ).json()
    assert promoted["source_url"] == BLUE
    assert "extra_sources" not in promoted["resolution_json"]
    # … et sa couleur devient celle de la fiche principale.
    assert promoted["resolution_json"]["main_color"] == "Bleu"
    assert {e.get("color") for e in promoted["staged_images_json"]} == {"Bleu"}
    assert _urls(promoted) == [
        "https://cdn.example/blue-1.jpg",
        "https://cdn.example/blue-2.jpg",
        "https://cdn.example/pink-1.jpg",
    ]


@pytest.mark.usefixtures("pipeline")
def test_page_preview_allows_extra_sources(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import items as items_routes

    monkeypatch.setattr(items_routes, "fetch_page_preview", lambda url: f"{url}/og.jpg")
    item = _review_item(auth_client)
    assert (
        auth_client.get(
            f"/items/{item.id}/page-preview", params={"url": GREEN}
        ).status_code
        == 422
    )
    auth_client.post(
        f"/items/{item.id}/sources", json={"source_url": GREEN, "color": "Vert"}
    )
    resp = auth_client.get(f"/items/{item.id}/page-preview", params={"url": GREEN})
    assert resp.status_code == 200
    assert resp.json()["image_url"] == f"{GREEN}/og.jpg"


def test_normalize_and_revert_keep_color_tags(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.imaging.service as imaging_service
    from app.api.deps import get_photoroom_client
    from app.clients.photoroom import PhotoroomClient
    from app.main import app
    from tests.images import cutout_png, source_jpeg

    monkeypatch.setattr(imaging_service, "_download_source", lambda url: source_jpeg())
    item = _review_item(auth_client)
    db = _db()
    row = db.get(EnrichmentItem, item.id)
    assert row is not None
    tagged = {
        "url": "https://cdn.example/blue-1.jpg",
        "position": 2,
        "color": "Bleu",
        "source_page": BLUE,
    }
    row.staged_images_json = [*(row.staged_images_json or []), tagged]
    db.commit()

    photoroom = PhotoroomClient(
        "pr-key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=cutout_png())
        ),
    )
    app.dependency_overrides[get_photoroom_client] = lambda: photoroom
    try:
        resp = auth_client.post(
            f"/items/{item.id}/images/normalize", json={"url": tagged["url"]}
        )
        assert resp.status_code == 200, resp.text
        normalized = resp.json()["staged_images_json"][1]
        assert normalized["asset_id"]
        assert normalized["color"] == "Bleu"
        assert normalized["source_page"] == BLUE

        back = auth_client.post(
            f"/items/{item.id}/images/normalize",
            json={"url": normalized["url"], "revert": True},
        )
        assert back.status_code == 200
        assert back.json()["staged_images_json"][1] == tagged
    finally:
        app.dependency_overrides.pop(get_photoroom_client, None)
