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
    monkeypatch.setattr(deps, "_company_clients", {})
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
