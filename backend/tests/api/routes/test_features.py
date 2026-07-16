"""Modules par compte : gardes 403 feature_disabled + protection admin-only."""

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Account, User


@pytest.fixture
def db(db_session_factory: sessionmaker[Session]) -> Generator[Session]:
    session = db_session_factory()
    yield session
    session.close()


def _disable_features(db: Session, user_email: str, **flags: bool) -> None:
    user = db.query(User).filter(User.email == user_email).one()
    assert user.account_id is not None
    account = db.get(Account, user.account_id)
    assert account is not None
    account.settings_json = {**(account.settings_json or {}), **flags}
    db.commit()


def test_import_module_off_blocks_imports_and_profiles(
    auth_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    # Matérialise le compte (premier accès) puis coupe le module.
    assert auth_client.get("/stats/dashboard").status_code == 200
    _disable_features(db, test_user["email"], feature_import=False)

    for call in (
        auth_client.get("/imports"),
        auth_client.get("/import-profiles"),
    ):
        assert call.status_code == 403
        assert call.json()["code"] == "feature_disabled"


def test_enrich_module_off_blocks_jobs_and_items(
    auth_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    assert auth_client.get("/stats/dashboard").status_code == 200
    _disable_features(db, test_user["email"], feature_enrich=False)

    jobs = auth_client.post("/jobs", json={"selection": {"ids": [1]}})
    assert jobs.status_code == 403
    assert jobs.json()["code"] == "feature_disabled"
    assert auth_client.get("/items/1").status_code == 403


def test_studio_module_off_blocks_imaging_but_not_catalog(
    auth_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    assert auth_client.get("/stats/dashboard").status_code == 200
    _disable_features(db, test_user["email"], feature_studio=False)

    normalize = auth_client.post(
        "/products/101/images/normalize", json={"image_url": "https://x/i.jpg"}
    )
    assert normalize.status_code == 403
    assert normalize.json()["code"] == "feature_disabled"
    assert auth_client.get("/imaging/assets/pending-products").status_code == 403
    # La recherche catalogue et l'upload d'images restent du socle : la garde
    # ne doit pas les toucher (503 = Xano non configuré dans les tests, pas
    # 403 — la requête a passé la garde).
    assert auth_client.get("/products").status_code == 503


def test_features_default_on_and_visible_in_stats(auth_client: TestClient) -> None:
    stats = auth_client.get("/stats/dashboard").json()
    assert stats["feature_import"] is True
    assert stats["feature_enrich"] is True
    assert stats["feature_studio"] is True


def test_client_cannot_grant_itself_a_module(
    auth_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    assert auth_client.get("/stats/dashboard").status_code == 200
    _disable_features(db, test_user["email"], feature_enrich=False)

    # Le PUT client renvoie 200 mais préserve les champs opérateur.
    current = auth_client.get("/settings/account").json()
    current["feature_enrich"] = True
    assert auth_client.put("/settings/account", json=current).status_code == 200
    assert auth_client.get("/settings/account").json()["feature_enrich"] is False


def test_admin_bypasses_module_guards(
    admin_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    assert admin_client.get("/stats/dashboard").status_code == 200
    _disable_features(db, test_user["email"], feature_import=False)

    # L'admin plateforme passe (support/debug indépendant de l'offre).
    assert admin_client.get("/imports").status_code == 200


def test_dashboard_features_reflect_the_client_offer(
    auth_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    assert auth_client.get("/stats/dashboard").status_code == 200
    _disable_features(
        db, test_user["email"], feature_import=False, feature_studio=False
    )

    stats = auth_client.get("/stats/dashboard").json()
    assert stats["feature_import"] is False
    assert stats["feature_studio"] is False
    assert stats["feature_enrich"] is True


def test_dashboard_features_all_true_for_admin(
    admin_client: TestClient, test_user: dict[str, Any], db: Session
) -> None:
    """Miroir UI du bypass serveur : les flags de /stats/dashboard sont TOUS
    vrais pour l'admin, quel que soit le compte auquel il est rattaché —
    sinon l'interface masquerait des gestes que l'API autorise (support/
    prestation sur les comptes clients, demande Marc 2026-07-17)."""
    assert admin_client.get("/stats/dashboard").status_code == 200
    _disable_features(
        db, test_user["email"], feature_import=False, feature_studio=False
    )

    stats = admin_client.get("/stats/dashboard").json()
    assert stats["feature_import"] is True
    assert stats["feature_studio"] is True
    assert stats["feature_enrich"] is True
