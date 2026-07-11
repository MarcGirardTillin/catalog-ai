# ruff: noqa: E402, I001
from collections.abc import Generator
import os
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_DB", "test")

import app.main as main_module
from app.api.deps import get_db
from app.api.services.users import create_user
from app.main import app
from app.models import Base

TEST_USER_EMAIL = "dev@catalogai.io"
TEST_USER_PASSWORD = "password123"


@pytest.fixture(autouse=True)
def _disable_xano() -> Generator[None]:
    """Keep tests offline: the dev .env may carry real Xano creds, which would
    otherwise make the auth Xano-fallback (and product routes) hit the live API.
    Tests that exercise Xano re-enable it explicitly with monkeypatch."""
    from app.core.config import settings

    original = settings.XANO_BASE_URL
    settings.XANO_BASE_URL = ""
    yield
    settings.XANO_BASE_URL = original


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient]:
    def override_get_db() -> Generator[Session]:
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Default to a no-op background runner so job creation doesn't drain the
    # queue synchronously (TestClient runs background tasks inline). Tests that
    # exercise the trigger override this with a spy.
    from app.api.deps import get_job_runner

    app.dependency_overrides[get_job_runner] = lambda: lambda job_id: None
    main_module_any = cast(Any, main_module)
    original_ping_database = main_module_any.ping_database
    main_module_any.ping_database = lambda: True
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        main_module_any.ping_database = original_ping_database
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session_factory: sessionmaker[Session]) -> dict[str, Any]:
    """Seed one active user and return its credentials."""
    db = db_session_factory()
    try:
        user = create_user(db, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD)
        return {"id": user.id, "email": user.email, "password": TEST_USER_PASSWORD}
    finally:
        db.close()


@pytest.fixture
def auth_client(client: TestClient, test_user: dict[str, Any]) -> TestClient:
    """A TestClient with a valid session cookie for the seeded user."""
    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def admin_client(
    client: TestClient,
    test_user: dict[str, Any],
    db_session_factory: sessionmaker[Session],
) -> TestClient:
    """A TestClient signed in as the seeded user, promoted platform admin."""
    from sqlalchemy import update

    from app.models import User

    db = db_session_factory()
    try:
        db.execute(
            update(User).where(User.email == test_user["email"]).values(is_admin=True)
        )
        db.commit()
    finally:
        db.close()
    response = client.post(
        "/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    assert response.status_code == 200
    return client
