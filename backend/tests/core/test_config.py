"""Tests for the assembled settings (DSN shape, CORS parsing)."""

from app.core.config import Settings

_PG = {
    "POSTGRES_SERVER": "db.example.net",
    "POSTGRES_PORT": 12345,
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "secret",
    "POSTGRES_DB": "catalog",
}


def _settings(**overrides: object) -> Settings:
    # Explicit kwargs win over the repo .env, keeping these hermetic.
    return Settings(**{**_PG, **overrides})  # type: ignore[arg-type]


def test_database_uri_without_sslmode_has_no_query() -> None:
    """Default (local Docker database): libpq decides, no query appended."""
    uri = str(_settings().SQLALCHEMY_DATABASE_URI)
    assert uri == "postgresql+psycopg://app:secret@db.example.net:12345/catalog"


def test_database_uri_appends_sslmode_when_set() -> None:
    """Managed database over the network: TLS is required explicitly."""
    uri = str(_settings(POSTGRES_SSLMODE="require").SQLALCHEMY_DATABASE_URI)
    assert uri.endswith("/catalog?sslmode=require")


def test_cors_origins_are_split_trimmed_and_deduplicated() -> None:
    settings = _settings(
        BACKEND_CORS_ORIGINS=" https://a.example , https://b.example ,https://a.example,"
    )
    assert settings.BACKEND_CORS_ORIGIN_LIST == [
        "https://a.example",
        "https://b.example",
    ]
