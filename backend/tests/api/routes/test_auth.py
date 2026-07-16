"""Tests for the authentication routes and session cookie."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_login_sets_cookie_and_returns_user(
    client: TestClient, test_user: dict[str, Any]
) -> None:
    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )

    assert response.status_code == 200
    assert response.json()["email"] == test_user["email"]
    assert settings.AUTH_COOKIE_NAME in response.cookies


def test_login_with_wrong_password_is_401(
    client: TestClient, test_user: dict[str, Any]
) -> None:
    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def _enable_xano(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "XANO_BASE_URL", "https://tillin.test/api")
    monkeypatch.setattr(settings, "XANO_LOGIN_EMAIL", "svc@tillin.fr")
    monkeypatch.setattr(settings, "XANO_LOGIN_PASSWORD", "secret")


def test_login_falls_back_to_xano_and_creates_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_xano(monkeypatch)
    monkeypatch.setattr(
        "app.api.routes.auth.verify_login",
        lambda *a, **k: {"email": "buyer@tillin.fr", "full_name": "Buyer"},
    )

    response = client.post(
        "/auth/login", json={"email": "buyer@tillin.fr", "password": "xano-pw"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "buyer@tillin.fr"
    assert response.json()["full_name"] == "Buyer"
    assert settings.AUTH_COOKIE_NAME in response.cookies
    # The federated user is now a local user and can be resolved by the cookie.
    assert client.get("/auth/me").json()["email"] == "buyer@tillin.fr"


def test_login_rejects_when_xano_also_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_xano(monkeypatch)
    monkeypatch.setattr("app.api.routes.auth.verify_login", lambda *a, **k: None)

    response = client.post(
        "/auth/login", json={"email": "nobody@tillin.fr", "password": "nope"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_me_returns_current_user_when_logged_in(
    auth_client: TestClient, test_user: dict[str, Any]
) -> None:
    response = auth_client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == test_user["id"]


def test_logout_clears_session(
    auth_client: TestClient,
) -> None:
    assert auth_client.get("/auth/me").status_code == 200

    logout = auth_client.post("/auth/logout")
    assert logout.status_code == 204

    assert auth_client.get("/auth/me").status_code == 401


def test_invalid_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set(settings.AUTH_COOKIE_NAME, "not-a-jwt")

    response = client.get("/auth/me")

    assert response.status_code == 401


# --- Multi-entreprises : rattachement compte + capture du token au login ----


def _xano_profile(email: str, company_id: int, token: str) -> dict[str, Any]:
    return {
        "email": email,
        "full_name": "Xano User",
        "token": token,
        "company_id": company_id,
    }


def test_xano_login_attaches_company_account_and_token(
    client: TestClient,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_xano(monkeypatch)
    monkeypatch.setattr(
        "app.api.routes.auth.verify_login",
        lambda *a, **k: _xano_profile("buyer@jbs.fr", 51, "tok-jbs-1"),
    )

    response = client.post(
        "/auth/login", json={"email": "buyer@jbs.fr", "password": "xano-pw"}
    )
    assert response.status_code == 200

    from app.models import Account, User

    db = db_session_factory()
    try:
        user = db.query(User).filter(User.email == "buyer@jbs.fr").one()
        account = db.get(Account, user.account_id)
        assert account is not None
        assert account.xano_company_id == 51
        assert user.xano_token == "tok-jbs-1"
        assert user.xano_token_at is not None
    finally:
        db.close()


def test_two_companies_get_two_accounts(
    client: TestClient,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_xano(monkeypatch)
    profiles = {
        "a@neiwa.fr": _xano_profile("a@neiwa.fr", 40, "tok-neiwa"),
        "b@jbs.fr": _xano_profile("b@jbs.fr", 51, "tok-jbs"),
    }
    monkeypatch.setattr(
        "app.api.routes.auth.verify_login",
        lambda _url, email, _pw, **k: profiles[email],
    )

    for email in profiles:
        assert (
            client.post(
                "/auth/login", json={"email": email, "password": "pw"}
            ).status_code
            == 200
        )

    from app.models import User

    db = db_session_factory()
    try:
        a = db.query(User).filter(User.email == "a@neiwa.fr").one()
        b = db.query(User).filter(User.email == "b@jbs.fr").one()
        assert a.account_id != b.account_id
    finally:
        db.close()


def test_local_login_captures_xano_identity_when_credentials_match(
    client: TestClient,
    test_user: dict[str, Any],
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Un utilisateur LOCAL dont les identifiants passent aussi côté Xano
    # récupère un token et bascule sur le compte de son entreprise.
    _enable_xano(monkeypatch)
    monkeypatch.setattr(
        "app.api.routes.auth.verify_login",
        lambda *a, **k: _xano_profile(test_user["email"], 40, "tok-fresh"),
    )

    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    assert response.status_code == 200

    from app.models import Account, User

    db = db_session_factory()
    try:
        user = db.get(User, test_user["id"])
        assert user.xano_token == "tok-fresh"
        account = db.get(Account, user.account_id)
        assert account.xano_company_id == 40
    finally:
        db.close()


def test_local_login_still_works_when_xano_rejects(
    client: TestClient,
    test_user: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mot de passe local valide mais inconnu de Xano (opérateur/dev) : le
    # login passe, sans token — l'utilisateur reste sur son compte actuel.
    _enable_xano(monkeypatch)
    monkeypatch.setattr("app.api.routes.auth.verify_login", lambda *a, **k: None)

    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    assert response.status_code == 200


def test_company_account_is_named_after_the_company(
    client: TestClient,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_xano(monkeypatch)
    profile = _xano_profile("buyer@jbs.fr", 51, "tok-jbs")
    profile["company_name"] = "JBS ACCESSOIRES"
    monkeypatch.setattr("app.api.routes.auth.verify_login", lambda *a, **k: profile)

    assert (
        client.post(
            "/auth/login", json={"email": "buyer@jbs.fr", "password": "pw"}
        ).status_code
        == 200
    )

    from app.models import Account, User

    db = db_session_factory()
    try:
        user = db.query(User).filter(User.email == "buyer@jbs.fr").one()
        account = db.get(Account, user.account_id)
        assert account.name == "JBS ACCESSOIRES"
        # Le seeding tarifaire lit le PLUS ANCIEN compte (ici celui du
        # conftest crédits) sans en créer d'autre : exactement 2 comptes.
        assert db.query(Account).count() == 2
    finally:
        db.close()


def test_company_account_seeds_usage_price_grid_from_oldest_account(
    client: TestClient,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`usage_price` is a separate table from `settings_json` — it must be
    copied too, or a fresh company account has NO € cost grid at all (seen
    live: the admin usage screen reported it missing for JoggingJogging)."""
    from app.api.services.accounts import get_or_create_default_account
    from app.models import Account, UsagePrice, User

    db = db_session_factory()
    try:
        default_account = get_or_create_default_account(db)
        db.add(
            UsagePrice(
                account_id=default_account.id,
                provider="claude",
                model=None,
                metric="input_tokens",
                unit_price=3,
            )
        )
        db.commit()
    finally:
        db.close()

    _enable_xano(monkeypatch)
    profile = _xano_profile("buyer@jbs.fr", 51, "tok-jbs")
    monkeypatch.setattr("app.api.routes.auth.verify_login", lambda *a, **k: profile)
    assert (
        client.post(
            "/auth/login", json={"email": "buyer@jbs.fr", "password": "pw"}
        ).status_code
        == 200
    )

    db = db_session_factory()
    try:
        user = db.query(User).filter(User.email == "buyer@jbs.fr").one()
        account = db.get(Account, user.account_id)
        assert account is not None
        prices = db.query(UsagePrice).filter(UsagePrice.account_id == account.id).all()
        assert len(prices) == 1
        assert prices[0].provider == "claude"
        assert prices[0].metric == "input_tokens"
    finally:
        db.close()


def test_placeholder_account_upgraded_to_company_name_on_next_login(
    client: TestClient,
    db_session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_xano(monkeypatch)
    # Premier login : nom de company indisponible -> placeholder.
    first = _xano_profile("buyer@jbs.fr", 51, "tok-1")
    monkeypatch.setattr("app.api.routes.auth.verify_login", lambda *a, **k: first)
    client.post("/auth/login", json={"email": "buyer@jbs.fr", "password": "pw"})

    from app.models import Account

    db = db_session_factory()
    try:
        assert (
            db.query(Account).filter(Account.xano_company_id == 51).one().name
            == "Entreprise 51"
        )
    finally:
        db.close()

    # Second login : le nom arrive -> le placeholder est promu.
    second = _xano_profile("buyer@jbs.fr", 51, "tok-2")
    second["company_name"] = "JBS ACCESSOIRES"
    monkeypatch.setattr("app.api.routes.auth.verify_login", lambda *a, **k: second)
    client.post("/auth/login", json={"email": "buyer@jbs.fr", "password": "pw"})

    db = db_session_factory()
    try:
        assert (
            db.query(Account).filter(Account.xano_company_id == 51).one().name
            == "JBS ACCESSOIRES"
        )
    finally:
        db.close()
