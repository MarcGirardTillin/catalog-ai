"""Serveur MCP : jetons d'API personnels, authentification HTTP et outils.

Les outils sont appelés via le client MCP en mémoire de FastMCP, avec
l'utilisateur du jeton injecté (`get_access_token`) ; l'authentification
HTTP (bearer) est testée à part sur `/mcp`.
"""

from collections.abc import AsyncIterator, Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from sqlalchemy.orm import Session, sessionmaker

import app.mcp.auth as mcp_auth
import app.mcp.guard as mcp_guard
import app.mcp.server as mcp_server
from app.api.routes import imports as import_routes
from app.api.routes import items as item_routes
from app.api.services.api_tokens import authenticate_api_token
from app.mcp.oauth import ALL_SCOPES
from app.models import Account, ApiToken, CreditEntry, EnrichmentJob, User


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.fixture(autouse=True)
def _mcp_sessions(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le serveur MCP ouvre ses propres sessions : base de test + pas de worker."""
    monkeypatch.setattr(mcp_guard, "SessionLocal", db_session_factory)
    monkeypatch.setattr(mcp_auth, "SessionLocal", db_session_factory)
    monkeypatch.setattr(mcp_server, "job_runner", lambda: lambda job_id: None)


@pytest.fixture
def db(db_session_factory: sessionmaker[Session]) -> Generator[Session]:
    session = db_session_factory()
    yield session
    session.close()


def _user(db: Session, email: str) -> User:
    return db.query(User).filter(User.email == email).one()


@pytest.fixture
def as_user(
    auth_client: TestClient,
    test_user: dict[str, Any],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> User:
    """Outils appelés au nom de l'utilisateur de test (compte matérialisé)."""
    assert auth_client.get("/stats/dashboard").status_code == 200
    user = _user(db, test_user["email"])
    token = AccessToken(
        token="t", client_id="c", scopes=list(ALL_SCOPES), claims={"user_id": user.id}
    )
    monkeypatch.setattr(mcp_guard, "get_access_token", lambda: token)
    return user


@pytest.fixture
async def mcp_client() -> AsyncIterator[Client[Any]]:
    async with Client(mcp_server.mcp) as client:
        yield client


async def _call(client: Client[Any], name: str, **args: Any) -> dict[str, Any]:
    result = await client.call_tool(name, args)
    data: dict[str, Any] = result.structured_content or {}
    return data


def _set_flags(db: Session, user: User, **flags: bool) -> None:
    db.refresh(user)
    account = db.get(Account, user.account_id)
    assert account is not None
    account.settings_json = {**(account.settings_json or {}), **flags}
    db.commit()


# --- Jetons d'API ----------------------------------------------------------------


def test_api_tokens_create_list_revoke(auth_client: TestClient, db: Session) -> None:
    created = auth_client.post("/api-tokens", json={"name": "Claude Code"})
    assert created.status_code == 201, created.text
    body = created.json()
    secret = body["secret"]
    assert secret.startswith(body["token"]["prefix"] + "_")
    assert body["token"]["active"] is True

    listing = auth_client.get("/api-tokens").json()
    assert [t["name"] for t in listing] == ["Claude Code"]
    assert "secret" not in listing[0]
    # Seul le hachage est stocké.
    row = db.get(ApiToken, body["token"]["id"])
    assert row is not None and secret not in (row.token_hash, row.prefix)
    assert authenticate_api_token(db, secret) is not None

    revoked = auth_client.delete(f"/api-tokens/{body['token']['id']}")
    assert revoked.status_code == 200
    assert revoked.json()["active"] is False
    db.expire_all()
    assert authenticate_api_token(db, secret) is None


def test_api_tokens_require_auth_and_are_per_user(
    client: TestClient, auth_client: TestClient, db: Session
) -> None:
    token_id = auth_client.post("/api-tokens", json={"name": "x"}).json()["token"]["id"]
    other = User(email="autre@tillin.fr", hashed_password="x", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)
    from app.api.exceptions import AppException
    from app.api.services.api_tokens import revoke_api_token

    with pytest.raises(AppException) as exc:
        revoke_api_token(db, other, token_id)
    assert exc.value.status_code == 404

    auth_client.post("/auth/logout")
    assert client.get("/api-tokens").status_code == 401


def test_expired_token_or_inactive_user_is_refused(
    auth_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    secret = auth_client.post("/api-tokens", json={"name": "x"}).json()["secret"]
    row = db.query(ApiToken).one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert authenticate_api_token(db, secret) is None

    row.expires_at = None
    user = _user(db, test_user["email"])
    user.is_active = False
    db.commit()
    assert authenticate_api_token(db, secret) is None
    assert authenticate_api_token(db, "pas-un-jeton") is None


# --- Authentification HTTP sur /mcp ---------------------------------------------


def test_mcp_http_requires_a_valid_bearer(auth_client: TestClient) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    no_token = auth_client.post("/mcp", headers=MCP_HEADERS, json=payload)
    assert no_token.status_code == 401
    assert no_token.headers["www-authenticate"].startswith("Bearer")

    bad = auth_client.post(
        "/mcp",
        headers={**MCP_HEADERS, "Authorization": "Bearer cat_faux_jeton"},
        json=payload,
    )
    assert bad.status_code == 401

    secret = auth_client.post("/api-tokens", json={"name": "Codex"}).json()["secret"]
    ok = auth_client.post(
        "/mcp",
        headers={**MCP_HEADERS, "Authorization": f"Bearer {secret}"},
        json=payload,
    )
    assert ok.status_code == 200, ok.text
    names = {tool["name"] for tool in ok.json()["result"]["tools"]}
    assert {"catalogai_search_products", "catalogai_transfer_import"} <= names


def test_every_tool_declares_annotations() -> None:
    import asyncio

    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert len(tools) == 22
    for tool in tools:
        assert tool.annotations is not None and tool.annotations.title, tool.name
        assert tool.annotations.read_only_hint is not None, tool.name
    destructive = {
        t.name for t in tools if t.annotations and t.annotations.destructive_hint
    }
    assert destructive == {
        "catalogai_apply_item",
        "catalogai_arrange_product_images",
        "catalogai_set_brand_websites",
        "catalogai_set_category_weights",
        "catalogai_transfer_import",
    }


# --- Outils -----------------------------------------------------------------------


@pytest.mark.anyio
async def test_account_overview(as_user: User, mcp_client: Client[Any]) -> None:
    data = await _call(mcp_client, "catalogai_get_account_overview")
    assert data["user"] == as_user.email
    assert set(data["modules"]) == {"import", "enrichment", "studio"}
    assert data["credits_balance"] > 0
    assert "enrich_item" in data["credit_costs"]


@pytest.mark.anyio
async def test_start_enrichment_creates_job_and_status(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    started = await _call(
        mcp_client, "catalogai_start_enrichment", product_ids=[11, 12]
    )
    assert started["items"] == 2
    assert started["estimated_credits"] > 0
    job = db.get(EnrichmentJob, started["job_id"])
    assert job is not None and job.account_id == as_user.account_id
    # Le lanceur est capturé comme pour l'API.
    assert job.config_json["launcher_user_id"] == as_user.id

    status = await _call(mcp_client, "catalogai_get_job_status", job_id=job.id)
    assert status["counts"]["total"] == 2
    review = await _call(
        mcp_client,
        "catalogai_list_items_to_review",
        job_id=job.id,
        status="ready_for_review",
    )
    assert review["total"] == 0


@pytest.mark.anyio
async def test_module_off_refuses_and_admin_bypasses(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    _set_flags(db, as_user, feature_enrich=False, feature_import=False)
    with pytest.raises(ToolError, match="enrichissement n'est pas activé"):
        await mcp_client.call_tool("catalogai_start_enrichment", {"product_ids": [1]})
    with pytest.raises(ToolError, match="import n'est pas activé"):
        await mcp_client.call_tool("catalogai_list_imports", {})

    as_user.is_admin = True
    db.merge(as_user)
    db.commit()
    data = await _call(mcp_client, "catalogai_list_imports")
    assert data["total"] == 0


@pytest.mark.anyio
async def test_admin_bypass_does_not_extend_to_credits(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    db.refresh(as_user)
    as_user.is_admin = True
    db.add(
        CreditEntry(
            account_id=as_user.account_id,
            kind="grant",
            credits=-5_000_000,
            label="dette",
        )
    )
    db.commit()
    with pytest.raises(ToolError, match="Crédits insuffisants"):
        await mcp_client.call_tool("catalogai_start_enrichment", {"product_ids": [1]})


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_other_account_job_is_not_visible(
    mcp_client: Client[Any], db: Session
) -> None:
    other = Account(name="autre boutique")
    db.add(other)
    db.commit()
    foreign = EnrichmentJob(
        account_id=other.id, job_type="enrichment", status="pending"
    )
    db.add(foreign)
    db.commit()
    with pytest.raises(ToolError, match="not_found|introuvable"):
        await mcp_client.call_tool("catalogai_get_job_status", {"job_id": foreign.id})


@pytest.mark.anyio
async def test_write_tools_preview_without_confirm(
    as_user: User, mcp_client: Client[Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = await _call(mcp_client, "catalogai_start_enrichment", product_ids=[21])
    from app.models import EnrichmentItem

    item = db.query(EnrichmentItem).filter_by(job_id=started["job_id"]).one()
    item.status = "approved"
    item.staged_title = "Nouveau titre"
    db.commit()

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("aucune écriture Tillin sans confirm")

    monkeypatch.setattr(item_routes, "apply_item_route", boom)
    monkeypatch.setattr(import_routes, "transfer_import", boom)

    preview = await _call(mcp_client, "catalogai_apply_item", item_id=item.id)
    assert preview["preview"] is True
    assert preview["will_write"]["proposed_title"] == "Nouveau titre"

    job = EnrichmentJob(
        account_id=as_user.account_id, job_type="import", status="completed"
    )
    db.add(job)
    db.commit()
    transfer = await _call(mcp_client, "catalogai_transfer_import", import_id=job.id)
    assert transfer["preview"] is True


@pytest.mark.anyio
async def test_inactive_user_is_refused(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    db.refresh(as_user)
    as_user.is_active = False
    db.commit()
    with pytest.raises(ToolError, match="désactivé"):
        await mcp_client.call_tool("catalogai_get_account_overview", {})


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_expired_tillin_session_says_what_to_do(
    mcp_client: Client[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.exceptions import AppException

    def expired(_db: Session, _user: User) -> Any:
        raise AppException(
            status_code=401, code="xano_token_expired", message="Session expired"
        )

    monkeypatch.setattr(mcp_guard, "xano_client_for_user", expired)
    with pytest.raises(ToolError, match="reconnectez-vous sur catalog.tillin.fr"):
        await mcp_client.call_tool("catalogai_search_products", {"query": "robe"})


class _FakeCatalog:
    """Tillin simulé : 2 marques, produits 31-32 chez Le Petit Souk."""

    def list_brands(self) -> list[Any]:
        from app.api.schemas import Brand

        return [
            Brand(id=7, name="Le Petit Souk"),
            Brand(id=8, name="Maileg"),
            Brand(id=9, name="Petit Bateau"),
        ]

    def search_products(self, **kwargs: Any) -> Any:
        from app.api.schemas import Product
        from app.clients.xano import ProductPage

        ids = {7: [31, 32], 8: [33]}.get(kwargs.get("brand") or 0, [31, 32, 33])
        items = [Product(id=i, title=f"Produit {i}") for i in ids]
        return ProductPage(items=items, total=len(items), page=1, per_page=100)


@pytest.fixture
def fake_catalog(monkeypatch: pytest.MonkeyPatch) -> _FakeCatalog:
    catalog = _FakeCatalog()
    monkeypatch.setattr(mcp_guard, "xano_client_for_user", lambda db, user: catalog)
    return catalog


def _processed_items(db: Session, user: User, product_ids: list[int]) -> int:
    from app.models import EnrichmentItem

    job = EnrichmentJob(
        account_id=user.account_id, job_type="enrichment", status="completed"
    )
    db.add(job)
    db.commit()
    now = datetime.now(UTC)
    for product_id in product_ids:
        db.add(
            EnrichmentItem(
                job_id=job.id,
                account_id=user.account_id,
                tillin_product_id=product_id,
                status="ready_for_review",
                product_title=f"Produit {product_id}",
                staged_title=f"Titre IA {product_id}",
                started_at=now - timedelta(minutes=2),
                finished_at=now - timedelta(minutes=1),
            )
        )
    # Une fiche traitée il y a 3 jours : hors « aujourd'hui ».
    db.add(
        EnrichmentItem(
            job_id=job.id,
            account_id=user.account_id,
            tillin_product_id=31,
            status="applied",
            started_at=now - timedelta(days=3),
            finished_at=now - timedelta(days=3),
        )
    )
    db.commit()
    return job.id


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_catalog")
async def test_enriched_products_today_filtered_by_brand_name(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    """Question de Marc : « produits Le Petit Souk enrichis aujourd'hui »."""
    _processed_items(db, as_user, [31, 32, 33])

    data = await _call(
        mcp_client,
        "catalogai_list_enriched_products",
        since="today",
        brand="le petit souk",
    )
    assert data["brand"] == {"id": 7, "name": "Le Petit Souk"}
    assert sorted(item["product_id"] for item in data["items"]) == [31, 32]
    assert {item["status"] for item in data["items"]} == {"ready_for_review"}
    assert data["items"][0]["proposed_title"].startswith("Titre IA")

    everything = await _call(mcp_client, "catalogai_list_enriched_products")
    assert len(everything["items"]) == 3  # celle d'il y a 3 jours exclue

    with pytest.raises(ToolError, match="Plusieurs marques"):
        await mcp_client.call_tool(
            "catalogai_list_enriched_products", {"brand": "petit"}
        )
    with pytest.raises(ToolError, match="Aucune marque"):
        await mcp_client.call_tool(
            "catalogai_list_enriched_products", {"brand": "zara"}
        )
    with pytest.raises(ToolError, match="Date illisible"):
        await mcp_client.call_tool(
            "catalogai_list_enriched_products", {"since": "demain"}
        )


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_catalog", "as_user")
async def test_brand_tools_and_search_by_brand_name(mcp_client: Client[Any]) -> None:
    brands = await _call(mcp_client, "catalogai_list_brands", query="petit")
    assert [b["name"] for b in brands["brands"]] == ["Le Petit Souk", "Petit Bateau"]

    found = await _call(mcp_client, "catalogai_search_products", brand="Maileg")
    assert [p["id"] for p in found["products"]] == [33]


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_search_summary_carries_stock_and_origins(
    mcp_client: Client[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.schemas import Product, ProductVariant
    from app.clients.xano import ProductPage

    captured: dict[str, Any] = {}

    class Catalog:
        def search_products(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            items = [
                Product(
                    id=51,
                    variants=[
                        ProductVariant(stock_quantity=2),
                        ProductVariant(stock_quantity=3),
                        ProductVariant(),
                    ],
                    origins=["Shopify"],
                ),
                Product(id=52, variants=[ProductVariant()]),
            ]
            return ProductPage(items=items, total=2, page=1, per_page=100)

    monkeypatch.setattr(mcp_guard, "xano_client_for_user", lambda db, user: Catalog())
    found = await _call(mcp_client, "catalogai_search_products", per_page=100)
    assert captured["per_page"] == 100
    summaries = {p["id"]: p for p in found["products"]}
    assert summaries[51]["stock"] == 5
    assert summaries[51]["origins"] == ["Shopify"]
    # Aucune variante suivie : stock inconnu, pas 0 ; aucune connexion.
    assert summaries[52]["stock"] is None
    assert summaries[52]["origins"] == []


@pytest.mark.anyio
async def test_list_enrichments_by_day(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    job_id = _processed_items(db, as_user, [41])
    today = await _call(mcp_client, "catalogai_list_enrichments", since="today")
    assert [e["job_id"] for e in today["enrichments"]] == [job_id]
    old = await _call(
        mcp_client, "catalogai_list_enrichments", since="2020-01-01", until="2020-01-31"
    )
    assert old["total"] == 0


# --- Images produit ---------------------------------------------------------------


class _FakeGallery:
    """Tillin simulé pour les images : produit 60 avec deux images (1, 2)."""

    def __init__(self) -> None:
        self.next_id = 100
        self.uploaded: list[tuple[int, str]] = []
        self.deactivated: list[int] = []
        self.positions: list[tuple[int, int]] = []

    def get_product(self, product_id: int) -> Any:
        from app.api.schemas import Product, ProductImage

        if product_id != 60:
            return None
        images = [
            ProductImage(id=1, url="https://cdn/1.jpg", position=1),
            ProductImage(id=2, url="https://cdn/2.jpg", position=2),
        ]
        return Product(id=60, title="Bob", images=images)

    def _created(self, count: int) -> list[Any]:
        from app.api.schemas import ProductImage

        created = []
        for _ in range(count):
            self.next_id += 1
            created.append(
                ProductImage(id=self.next_id, url=f"https://cdn/{self.next_id}.jpg")
            )
        return created

    def upload_product_images(self, product_id: int, files: list[Any]) -> list[Any]:
        self.uploaded.extend((product_id, name) for name, _, _ in files)
        return self._created(len(files))

    def add_product_images(self, product_id: int, urls: list[str]) -> list[Any]:
        # Tillin avale un échec sur deux.
        return self._created(len(urls) // 2)

    def deactivate_product_images(self, ids: list[int]) -> None:
        self.deactivated.extend(ids)

    def set_product_image_positions(self, positions: list[tuple[int, int]]) -> None:
        self.positions = list(positions)


@pytest.fixture
def gallery(monkeypatch: pytest.MonkeyPatch) -> _FakeGallery:
    import app.api.routes.mcp_uploads as upload_routes

    fake = _FakeGallery()
    monkeypatch.setattr(mcp_guard, "xano_client_for_user", lambda db, user: fake)
    monkeypatch.setattr(upload_routes, "xano_client_for_user", lambda db, user: fake)
    return fake


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_local_image_upload_round_trip(
    mcp_client: Client[Any], client: TestClient, gallery: _FakeGallery
) -> None:
    from tests.images import source_jpeg

    issued = await _call(
        mcp_client,
        "catalogai_create_image_upload",
        product_id=60,
        filenames=["C:\\photos\\packshot.jpg"],
    )
    upload = issued["uploads"][0]
    assert upload["filename"] == "packshot.jpg"
    path = upload["upload_url"].split("/mcp-uploads/", 1)[1]

    response = client.put(f"/mcp-uploads/{path}", content=source_jpeg())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product_id"] == 60 and body["image_id"] == 101
    assert gallery.uploaded == [(60, "packshot.jpg")]

    # Pas une image : refus explicite, rien n'est envoyé à Tillin.
    refused = client.put(f"/mcp-uploads/{path}", content=b"not an image")
    assert refused.status_code == 422
    assert len(gallery.uploaded) == 1


@pytest.mark.anyio
async def test_upload_link_rejects_forged_and_session_tokens(
    as_user: User, client: TestClient, gallery: _FakeGallery
) -> None:
    from app.core.security.tokens import create_access_token, decode_access_token
    from app.mcp.uploads import UploadGrant, sign_upload

    session = create_access_token(as_user.id)
    assert client.put(f"/mcp-uploads/{session}", content=b"x").status_code == 401
    assert client.put("/mcp-uploads/abc", content=b"x").status_code == 401
    # Et un lien d'envoi ne vaut pas cookie de session (audience dédiée).
    grant = UploadGrant(as_user.id, as_user.account_id or 0, 60, "a.jpg")
    assert decode_access_token(sign_upload(grant)) is None
    expired = sign_upload(grant, now=datetime.now(UTC) - timedelta(hours=1))
    assert client.put(f"/mcp-uploads/{expired}", content=b"x").status_code == 401
    assert gallery.uploaded == []


@pytest.mark.anyio
async def test_upload_link_refused_after_account_switch(
    as_user: User, client: TestClient, gallery: _FakeGallery, db: Session
) -> None:
    from app.mcp.uploads import UploadGrant, sign_upload
    from tests.images import source_jpeg

    db.refresh(as_user)
    link = sign_upload(UploadGrant(as_user.id, as_user.account_id or 0, 60, "a.jpg"))
    other = Account(name="Autre boutique")
    db.add(other)
    db.commit()
    as_user.account_id = other.id
    db.commit()
    response = client.put(f"/mcp-uploads/{link}", content=source_jpeg())
    assert response.status_code == 409
    assert gallery.uploaded == []


@pytest.mark.anyio
@pytest.mark.usefixtures("gallery")
async def test_image_upload_requires_write_scope(
    as_user: User,
    mcp_client: Client[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mcp.oauth import SCOPE_READ

    token = AccessToken(
        token="t", client_id="c", scopes=[SCOPE_READ], claims={"user_id": as_user.id}
    )
    monkeypatch.setattr(mcp_guard, "get_access_token", lambda: token)
    with pytest.raises(ToolError, match="lecture seule"):
        await mcp_client.call_tool(
            "catalogai_create_image_upload", {"product_id": 60, "filenames": ["a.jpg"]}
        )


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user", "gallery")
async def test_add_images_from_urls_reports_missing(mcp_client: Client[Any]) -> None:
    added = await _call(
        mcp_client,
        "catalogai_add_product_images",
        product_id=60,
        image_urls=["https://a/1.jpg", "https://a/2.jpg"],
    )
    assert added["requested"] == 2 and added["not_created"] == 1
    with pytest.raises(ToolError, match="non http"):
        await mcp_client.call_tool(
            "catalogai_add_product_images",
            {"product_id": 60, "image_urls": ["file:///c/a.jpg"]},
        )


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_arrange_images_previews_then_replaces(
    mcp_client: Client[Any], gallery: _FakeGallery
) -> None:
    preview = await _call(
        mcp_client,
        "catalogai_arrange_product_images",
        product_id=60,
        image_ids=[2],
        remove_others=True,
    )
    assert preview["preview"] is True and preview["will_remove"] == [1]
    assert gallery.deactivated == [] and gallery.positions == []

    await _call(
        mcp_client,
        "catalogai_arrange_product_images",
        product_id=60,
        image_ids=[2],
        remove_others=True,
        confirm=True,
    )
    assert gallery.deactivated == [1]
    assert gallery.positions == [(2, 1)]

    # Réordonner sans retirer : les non listées suivent.
    await _call(
        mcp_client,
        "catalogai_arrange_product_images",
        product_id=60,
        image_ids=[2],
        confirm=True,
    )
    assert gallery.positions == [(2, 1), (1, 2)]
    with pytest.raises(ToolError, match="inconnues"):
        await mcp_client.call_tool(
            "catalogai_arrange_product_images", {"product_id": 60, "image_ids": [99]}
        )


# --- Prompts ------------------------------------------------------------------------


def _prompt(db: Session, account_id: int | None, name: str, *categories: str) -> int:
    from app.models import InstructionTemplate

    row = InstructionTemplate(
        account_id=account_id,
        name=name,
        content=f"Consignes {name}",
        categories_json=list(categories),
    )
    db.add(row)
    db.commit()
    return row.id


@pytest.mark.anyio
async def test_list_prompts_scoped_to_account(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    db.refresh(as_user)
    mine = _prompt(db, as_user.account_id, "Livres", "Livres")
    other = Account(name="Autre boutique")
    db.add(other)
    db.commit()
    _prompt(db, other.id, "Secret")

    listed = await _call(mcp_client, "catalogai_list_prompts")
    assert [p["prompt_id"] for p in listed["prompts"]] == [mine]
    assert listed["prompts"][0]["categories"] == ["Livres"]


@pytest.mark.anyio
async def test_start_enrichment_one_job_per_prompt(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    db.refresh(as_user)
    books = _prompt(db, as_user.account_id, "Livres")
    toys = _prompt(db, as_user.account_id, "Jouets")

    started = await _call(
        mcp_client,
        "catalogai_start_enrichment",
        product_ids=[1, 2, 3],
        prompt_id=books,
        prompts={"3": toys},
        config={"seo_keywords": ["noël"]},
    )
    assert [(j["prompt_id"], j["items"]) for j in started["jobs"]] == [
        (books, 2),
        (toys, 1),
    ]
    job = db.get(EnrichmentJob, started["jobs"][1]["job_id"])
    assert job is not None
    # Prompt copié dans le job (instantané, comme depuis l'app).
    assert job.config_json["editorial_instructions"] == "Consignes Jouets"
    assert job.config_json["seo_keywords"] == ["noël"]


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_start_enrichment_rejects_bad_prompt_and_config_before_writing(
    mcp_client: Client[Any], db: Session
) -> None:
    other = Account(name="Autre boutique")
    db.add(other)
    db.commit()
    foreign = _prompt(db, other.id, "Secret")

    with pytest.raises(ToolError, match="introuvables"):
        await mcp_client.call_tool(
            "catalogai_start_enrichment", {"product_ids": [1], "prompt_id": foreign}
        )
    with pytest.raises(ToolError, match="inconnues"):
        await mcp_client.call_tool(
            "catalogai_start_enrichment",
            {"product_ids": [1], "config": {"ai_model": "opus"}},
        )
    with pytest.raises(ToolError, match="hors product_ids"):
        await mcp_client.call_tool(
            "catalogai_start_enrichment",
            {"product_ids": [1], "prompts": {"9": foreign}},
        )
    assert db.query(EnrichmentJob).count() == 0


# --- Poids par catégorie ------------------------------------------------------------


class _FakeCategories:
    """Tillin simulé : 5 sous-catégorie visible, 6 masquée, 7 en échec."""

    def __init__(self) -> None:
        self.written: list[dict[str, Any]] = []

    def get_classification(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "categories": [
                {
                    "id": 5,
                    "title": "Livres",
                    "parent_id": 2,
                    "visible": True,
                    "default_weight_kg": 0.3,
                },
                {"id": 6, "title": "Archives", "parent_id": 0, "visible": False},
                {"id": 7, "title": "Jouets", "parent_id": 0, "visible": True},
            ]
        }

    def set_category_default_weight(
        self, category_id: int, weight: float, **fields: Any
    ) -> None:
        from app.clients.xano import XanoError

        if category_id == 7:
            raise XanoError(message="refus Tillin")
        self.written.append({"id": category_id, "weight": weight, **fields})


@pytest.fixture
def categories(monkeypatch: pytest.MonkeyPatch) -> _FakeCategories:
    fake = _FakeCategories()
    monkeypatch.setattr(mcp_guard, "xano_client_for_user", lambda db, user: fake)
    return fake


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user", "categories")
async def test_list_category_weights_hides_masked(mcp_client: Client[Any]) -> None:
    listed = await _call(mcp_client, "catalogai_list_category_weights")
    assert [c["category_id"] for c in listed["categories"]] == [5, 7]
    assert listed["categories"][0]["default_weight_kg"] == 0.3
    found = await _call(mcp_client, "catalogai_list_category_weights", query="jou")
    assert [c["title"] for c in found["categories"]] == ["Jouets"]


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_set_category_weights_previews_then_writes(
    mcp_client: Client[Any], categories: _FakeCategories
) -> None:
    preview = await _call(
        mcp_client, "catalogai_set_category_weights", weights={"5": 0.5}
    )
    assert preview["preview"] is True
    assert preview["will_write"][0]["before_kg"] == 0.3
    assert categories.written == []

    done = await _call(
        mcp_client,
        "catalogai_set_category_weights",
        weights={"5": 0.5, "6": 0, "7": 1},
        confirm=True,
    )
    assert [c["category_id"] for c in done["updated"]] == [5, 6]
    assert done["failed"][0]["category_id"] == 7
    # Parent et visibilité renvoyés : l'endpoint remet les champs absents à zéro.
    assert categories.written[0] == {
        "id": 5,
        "weight": 0.5,
        "title": "Livres",
        "parent_id": 2,
        "visible": True,
    }
    assert categories.written[1]["visible"] is False


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_set_category_weights_refuses_before_writing(
    mcp_client: Client[Any], categories: _FakeCategories
) -> None:
    with pytest.raises(ToolError, match="inconnues"):
        await mcp_client.call_tool(
            "catalogai_set_category_weights",
            {"weights": {"5": 0.5, "99": 1}, "confirm": True},
        )
    with pytest.raises(ToolError, match="invalides"):
        await mcp_client.call_tool(
            "catalogai_set_category_weights",
            {"weights": {"5": -1}, "confirm": True},
        )
    with pytest.raises(ToolError, match="invalides"):
        await mcp_client.call_tool(
            "catalogai_set_category_weights",
            {"weights": {"5": 2500}, "confirm": True},
        )
    assert categories.written == []


@pytest.mark.anyio
@pytest.mark.usefixtures("categories")
async def test_category_weights_need_a_module(
    as_user: User, mcp_client: Client[Any], db: Session
) -> None:
    _set_flags(db, as_user, feature_import=False, feature_enrich=False)
    with pytest.raises(ToolError, match="doit être activé"):
        await mcp_client.call_tool("catalogai_list_category_weights", {})
    with pytest.raises(ToolError, match="doit être activé"):
        await mcp_client.call_tool(
            "catalogai_set_category_weights", {"weights": {"5": 1}, "confirm": True}
        )

    as_user.is_admin = True
    db.commit()
    listed = await _call(mcp_client, "catalogai_list_category_weights")
    assert listed["total"] == 2


@pytest.mark.anyio
@pytest.mark.usefixtures("categories")
async def test_set_category_weights_requires_write_scope(
    as_user: User, mcp_client: Client[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.mcp.oauth import SCOPE_READ

    token = AccessToken(
        token="t", client_id="c", scopes=[SCOPE_READ], claims={"user_id": as_user.id}
    )
    monkeypatch.setattr(mcp_guard, "get_access_token", lambda: token)
    with pytest.raises(ToolError, match="lecture seule"):
        await mcp_client.call_tool(
            "catalogai_set_category_weights", {"weights": {"5": 1}}
        )


# --- Sites des marques --------------------------------------------------------------


class _FakeBrands:
    """Tillin simulé : marque 7 avec deux sites, marque 8 sans site."""

    def __init__(self) -> None:
        self.written: list[tuple[int, list[str]]] = []

    def list_brands(self) -> list[Any]:
        from app.api.schemas import Brand

        return [
            Brand(
                id=7,
                name="Le Petit Souk",
                website_urls=["https://lepetitsouk.fr", "https://old.example.com"],
            ),
            Brand(id=8, name="Maileg"),
        ]

    def set_brand_website_urls(self, brand_id: int, urls: list[str]) -> None:
        self.written.append((brand_id, list(urls)))


@pytest.fixture
def brand_sites(monkeypatch: pytest.MonkeyPatch) -> _FakeBrands:
    fake = _FakeBrands()
    monkeypatch.setattr(mcp_guard, "xano_client_for_user", lambda db, user: fake)
    return fake


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user", "brand_sites")
async def test_list_brands_shows_websites(mcp_client: Client[Any]) -> None:
    listed = await _call(mcp_client, "catalogai_list_brands", query="souk")
    assert listed["brands"][0]["website_urls"][0] == "https://lepetitsouk.fr"


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_brand_websites_preview_then_add_and_remove(
    mcp_client: Client[Any], brand_sites: _FakeBrands
) -> None:
    preview = await _call(
        mcp_client,
        "catalogai_set_brand_websites",
        brand="Le Petit Souk",
        add=["new.example.com"],
        remove=["https://old.example.com/"],
    )
    expected = ["https://lepetitsouk.fr", "https://new.example.com"]
    assert preview["preview"] is True and preview["after"] == expected
    assert brand_sites.written == []

    done = await _call(
        mcp_client,
        "catalogai_set_brand_websites",
        brand_id=7,
        add=["new.example.com", "HTTP://LEPETITSOUK.FR"],
        remove=["old.example.com"],
        confirm=True,
    )
    assert done["updated"] is True
    assert brand_sites.written == [(7, expected)]


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_brand_websites_replace_and_clear(
    mcp_client: Client[Any], brand_sites: _FakeBrands
) -> None:
    await _call(
        mcp_client,
        "catalogai_set_brand_websites",
        brand_id=8,
        replace_with=["maileg.com"],
        confirm=True,
    )
    await _call(
        mcp_client,
        "catalogai_set_brand_websites",
        brand_id=7,
        replace_with=[],
        confirm=True,
    )
    assert brand_sites.written == [(8, ["https://maileg.com"]), (7, [])]


@pytest.mark.anyio
@pytest.mark.usefixtures("as_user")
async def test_brand_websites_refuses_before_writing(
    mcp_client: Client[Any], brand_sites: _FakeBrands
) -> None:
    bad_calls: list[tuple[dict[str, Any], str]] = [
        ({"brand_id": 99, "add": ["a.com"]}, "absente de ce catalogue"),
        ({"brand_id": 7}, "Précisez add"),
        ({"add": ["a.com"]}, "Précisez la marque"),
        ({"brand_id": 7, "brand": "Maileg", "add": ["a.com"]}, "Précisez la marque"),
        ({"brand_id": 7, "add": ["a.com"], "replace_with": []}, "ne se combine pas"),
        ({"brand_id": 7, "add": ["file:///c/a"]}, "invalides"),
        ({"brand_id": 7, "add": ["pasuneurl"]}, "invalides"),
        ({"brand_id": 7, "remove": ["absent.com"]}, "absentes"),
        ({"brand_id": 8, "add": [f"s{i}.com" for i in range(21)]}, "20 sites"),
    ]
    for args, message in bad_calls:
        with pytest.raises(ToolError, match=message):
            await mcp_client.call_tool(
                "catalogai_set_brand_websites", {**args, "confirm": True}
            )
    assert brand_sites.written == []


@pytest.mark.anyio
@pytest.mark.usefixtures("brand_sites")
async def test_brand_websites_need_enrich_module_and_write_scope(
    as_user: User,
    mcp_client: Client[Any],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mcp.oauth import SCOPE_READ

    args = {"brand_id": 7, "add": ["a.com"], "confirm": True}
    _set_flags(db, as_user, feature_enrich=False)
    with pytest.raises(ToolError, match="enrichissement n'est pas activé"):
        await mcp_client.call_tool("catalogai_set_brand_websites", args)

    _set_flags(db, as_user, feature_enrich=True)
    token = AccessToken(
        token="t", client_id="c", scopes=[SCOPE_READ], claims={"user_id": as_user.id}
    )
    monkeypatch.setattr(mcp_guard, "get_access_token", lambda: token)
    with pytest.raises(ToolError, match="lecture seule"):
        await mcp_client.call_tool("catalogai_set_brand_websites", args)
