"""xano_client_for_account : scoping par entreprise, repli service, rotation."""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.api.deps as deps
from app.api.exceptions import AppException
from app.api.services.users import create_user
from app.core.config import settings
from app.models import Account


@pytest.fixture(autouse=True)
def _xano_enabled_and_clean(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setattr(settings, "XANO_BASE_URL", "https://tillin.test/api")
    monkeypatch.setattr(settings, "XANO_LOGIN_EMAIL", "svc@tillin.fr")
    monkeypatch.setattr(settings, "XANO_LOGIN_PASSWORD", "secret")
    # Les caches module sont partagés entre tests : repartir à zéro.
    monkeypatch.setattr(deps, "_service_xano_client", None)
    monkeypatch.setattr(deps, "_token_clients", {})
    yield


@pytest.fixture
def db(db_session_factory: sessionmaker[Session]) -> Generator[Session]:
    session = db_session_factory()
    yield session
    session.close()


def _company_account(db: Session, company_id: int) -> Account:
    account = Account(name=f"Entreprise {company_id}", xano_company_id=company_id)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_company_account_without_token_is_401_not_service_fallback(
    db: Session,
) -> None:
    # Servir le catalogue du compte de service à une AUTRE entreprise serait
    # une fuite inter-tenants : on échoue explicitement.
    account = _company_account(db, 51)

    with pytest.raises(AppException) as excinfo:
        deps.xano_client_for_account(db, account.id)

    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "xano_token_expired"


def test_default_account_falls_back_to_service_identity(db: Session) -> None:
    account = Account(name="default")  # pas de company : opérateur/dev
    db.add(account)
    db.commit()

    client = deps.xano_client_for_account(db, account.id)

    assert client is deps.get_service_xano_client()


def test_token_client_is_cached_and_rotates_with_the_token(db: Session) -> None:
    account = _company_account(db, 51)
    user = create_user(db, email="buyer@jbs.fr", password="x")
    user.account_id = account.id
    user.xano_token = "tok-1"
    from datetime import UTC, datetime

    user.xano_token_at = datetime.now(UTC)
    db.commit()

    first = deps.xano_client_for_account(db, account.id)
    assert deps.xano_client_for_account(db, account.id) is first  # cache

    # Re-login : token rafraîchi -> nouveau client, l'ancien n'est pas resservi.
    user.xano_token = "tok-2"
    user.xano_token_at = datetime.now(UTC)
    db.commit()
    second = deps.xano_client_for_account(db, account.id)
    assert second is not first


def test_freshest_token_wins_across_the_account_users(db: Session) -> None:
    from datetime import UTC, datetime, timedelta

    account = _company_account(db, 51)
    old = create_user(db, email="old@jbs.fr", password="x")
    new = create_user(db, email="new@jbs.fr", password="x")
    old.account_id = new.account_id = account.id
    old.xano_token, old.xano_token_at = (
        "tok-old",
        datetime.now(UTC) - timedelta(hours=48),
    )
    new.xano_token, new.xano_token_at = "tok-new", datetime.now(UTC)
    db.commit()

    from app.api.services.accounts import freshest_company_token

    assert freshest_company_token(db, account.id) == "tok-new"


def test_admin_tokens_are_excluded_from_the_account_pool(db: Session) -> None:
    # Un admin plateforme peut changer d'entreprise dans Tillin : son token
    # ne représente pas le compte (incident Neiwa/Madel du 2026-07-30).
    from datetime import UTC, datetime, timedelta

    account = _company_account(db, 51)
    admin = create_user(db, email="ops@tillin.fr", password="x", is_admin=True)
    client_user = create_user(db, email="clement@neiwa.fr", password="x")
    admin.account_id = client_user.account_id = account.id
    admin.xano_token, admin.xano_token_at = "tok-admin", datetime.now(UTC)
    client_user.xano_token, client_user.xano_token_at = (
        "tok-client",
        datetime.now(UTC) - timedelta(hours=48),
    )
    db.commit()

    from app.api.services.accounts import freshest_company_token

    assert freshest_company_token(db, account.id) == "tok-client"


def test_interactive_client_uses_the_signed_in_users_own_token(db: Session) -> None:
    # Requêtes interactives : le token de l'utilisateur CONNECTÉ, jamais celui
    # d'un collègue plus « frais » (décision Marc 2026-07-30).
    from datetime import UTC, datetime, timedelta

    account = _company_account(db, 51)
    me = create_user(db, email="me@neiwa.fr", password="x")
    colleague = create_user(db, email="fresh@neiwa.fr", password="x")
    me.account_id = colleague.account_id = account.id
    me.xano_token, me.xano_token_at = (
        "tok-me",
        datetime.now(UTC) - timedelta(hours=48),
    )
    colleague.xano_token, colleague.xano_token_at = "tok-fresh", datetime.now(UTC)
    db.commit()

    mine = deps.xano_client_for_user(db, me)
    theirs = deps.xano_client_for_user(db, colleague)

    assert mine is not theirs
    assert deps.xano_client_for_user(db, me) is mine  # cache par token


def test_user_without_token_on_company_account_is_401(db: Session) -> None:
    account = _company_account(db, 51)
    user = create_user(db, email="expired@neiwa.fr", password="x")
    user.account_id = account.id
    db.commit()

    with pytest.raises(AppException) as excinfo:
        deps.xano_client_for_user(db, user)

    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "xano_token_expired"


def test_launcher_token_is_preferred_over_the_pool(db: Session) -> None:
    """Le token du LANCEUR du job (admin compris) prime sur le pool du compte.

    Incidents jobs 126/128 (2026-09-03) : le token du pool pointait sur une
    autre entreprise Tillin que celle des produits sélectionnés par le
    lanceur — « product not found at the source ».
    """
    from datetime import UTC, datetime

    account = _company_account(db, 61)
    colleague = create_user(db, email="pool@jogging.fr", password="x")
    admin = create_user(db, email="marc@tillin.fr", password="x")
    admin.is_admin = True
    colleague.account_id = admin.account_id = account.id
    colleague.xano_token = "tok-pool"
    colleague.xano_token_at = datetime.now(UTC)
    admin.xano_token = "tok-launcher"
    admin.xano_token_at = datetime.now(UTC)
    db.commit()

    from app.api.services.accounts import launcher_token

    # Lanceur admin : accepté ici (geste explicite), bien qu'exclu du pool.
    assert launcher_token(db, account.id, admin.id) == "tok-launcher"
    launcher = deps.xano_client_for_account(db, account.id, launcher_user_id=admin.id)
    assert launcher._token == "tok-launcher"  # noqa: SLF001

    # Sans lanceur (jobs anciens) : pool inchangé (admin toujours exclu).
    assert deps.xano_client_for_account(db, account.id)._token == "tok-pool"  # noqa: SLF001


def test_launcher_token_falls_back_to_the_pool(db: Session) -> None:
    from datetime import UTC, datetime

    account = _company_account(db, 62)
    other_account = _company_account(db, 63)
    colleague = create_user(db, email="pool@b62.fr", password="x")
    colleague.account_id = account.id
    colleague.xano_token = "tok-pool"
    colleague.xano_token_at = datetime.now(UTC)
    # Lanceur inutilisable : plus de token…
    dry = create_user(db, email="dry@b62.fr", password="x")
    dry.account_id = account.id
    # …ou rattaché à un AUTRE compte (jamais de fuite cross-entreprise)…
    stranger = create_user(db, email="s@b63.fr", password="x")
    stranger.account_id = other_account.id
    stranger.xano_token = "tok-stranger"
    stranger.xano_token_at = datetime.now(UTC)
    # …ou désactivé.
    gone = create_user(db, email="gone@b62.fr", password="x")
    gone.account_id = account.id
    gone.xano_token = "tok-gone"
    gone.xano_token_at = datetime.now(UTC)
    gone.is_active = False
    db.commit()

    for launcher_id in (dry.id, stranger.id, gone.id):
        client = deps.xano_client_for_account(
            db, account.id, launcher_user_id=launcher_id
        )
        assert client._token == "tok-pool"  # noqa: SLF001
