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
        token="t", client_id="c", scopes=[], claims={"user_id": user.id}
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
    assert len(tools) == 12
    for tool in tools:
        assert tool.annotations is not None and tool.annotations.title, tool.name
        assert tool.annotations.read_only_hint is not None, tool.name
    destructive = {
        t.name for t in tools if t.annotations and t.annotations.destructive_hint
    }
    assert destructive == {"catalogai_apply_item", "catalogai_transfer_import"}


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
